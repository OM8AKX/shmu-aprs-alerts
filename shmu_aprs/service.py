"""Hlavná logika služby – sťahovanie, filtrovanie, vysielanie, expirácia."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
import yaml

from .aprs_tx import AprsTransmitter
from .cap_parser import fetch_cap_alerts
from .html_fallback import fetch_html_alerts
from .districts import (
    offset_position,
    resolve_alert_positions,
    spread_collisions,
    lookup_district,
)
from .hydro import fetch_hydro_readings, readings_to_alerts, resolve_hydro_position, STATIONS
from .lightning import fetch_lightning_alerts, get_collector
from .models import ActiveObject, Alert, AlertLevel

log = logging.getLogger(__name__)


class ShmuAprsService:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.cfg = self._load_config()
        self.session = requests.Session()
        self.tx: Optional[AprsTransmitter] = None
        self.active: Dict[str, ActiveObject] = {}
        self._running = False
        self._last_beacon = datetime.min.replace(tzinfo=timezone.utc)
        self._last_poll = datetime.min.replace(tzinfo=timezone.utc)
        self._last_watchdog = time.monotonic()
        self.watchdog_enabled = self.cfg.get("watchdog", {}).get("enabled", False)
        self.watchdog_interval = self.cfg.get("watchdog", {}).get("interval_seconds", 60)
        self._notify_socket = os.environ.get("NOTIFY_SOCKET")
        # LGT identifier → (lat, lon)
        self._lightning_pos: Dict[str, Tuple[float, float]] = {}

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _setup_logging(self) -> None:
        level = getattr(logging, self.cfg.get("logging", {}).get("level", "INFO").upper())
        log_file = self.cfg.get("logging", {}).get("file")
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if log_file:
            try:
                log_path = Path(log_file)
                if str(log_path).startswith("/var/log/"):
                    alt = Path("/opt/shmu-aprs-alerts/logs") / log_path.name
                    try:
                        alt.parent.mkdir(parents=True, exist_ok=True)
                        log_path = alt
                    except OSError:
                        pass
                from logging.handlers import RotatingFileHandler

                class _SafeRotating(RotatingFileHandler):
                    def doRollover(self):
                        try:
                            super().doRollover()
                        except PermissionError as e:
                            print(f"Log rotate skipped: {e}", file=sys.stderr)

                handlers.append(_SafeRotating(
                    str(log_path),
                    maxBytes=self.cfg.get("logging", {}).get("max_bytes", 1_000_000),
                    backupCount=self.cfg.get("logging", {}).get("backup_count", 3),
                    encoding="utf-8",
                ))
            except OSError as e:
                print(f"Nemôžem otvoriť log súbor {log_file}: {e}", file=sys.stderr)
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=handlers,
            force=True,
        )

    def _notify(self, state: str) -> None:
        if not self._notify_socket:
            return
        try:
            import socket
            addr = self._notify_socket
            if addr.startswith("@"):
                addr = "\0" + addr[1:]
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.connect(addr)
            sock.sendall(state.encode())
            sock.close()
        except Exception as e:
            log.debug("systemd notify zlyhal: %s", e)

    def _lead_hours(self) -> float:
        return float(self.cfg.get("beacon", {}).get("lead_hours", 0))

    @staticmethod
    def _is_national(alert: Alert) -> bool:
        if not alert.areas and not alert.regions:
            return True
        national_kw = ("slovensko", "slovensk", "celoslovensk", "celá sr", "cela sr",
                       "nationwide", "whole country", "all regions")
        for area in alert.areas:
            low = area.lower()
            if any(k in low for k in national_kw):
                return True
        return False

    @staticmethod
    def _district_areas(alert: Alert) -> List[str]:
        out = []
        for area in alert.areas or []:
            if lookup_district(area):
                out.append(area)
        return out

    def _filter_alerts(self, alerts: List[Alert]) -> List[Alert]:
        flt = self.cfg.get("filter", {})
        districts = [d.lower() for d in flt.get("districts", [])]
        min_level = AlertLevel(flt.get("min_level", 1))
        lead = self._lead_hours()
        result = []
        for a in alerts:
            if a.identifier.startswith(("HYDRO-", "LGT-")):
                result.append(a)
                continue
            if a.level < min_level:
                continue
            if not a.is_active(lead_hours=lead):
                continue
            if self._is_national(a):
                log.info("Filter: preskakujem celoslovenskú %s", a.event)
                continue
            dist_areas = self._district_areas(a)
            if not dist_areas:
                log.debug("Filter: bez okresu – %s areas=%s", a.event, a.areas)
                continue
            if districts:
                match = False
                for area in dist_areas:
                    low = area.lower()
                    if any(d in low for d in districts):
                        match = True
                        break
                if not match:
                    continue
            a.areas = dist_areas
            a.regions = []
            result.append(a)
        log.info("Po filtri (iba okresy): %d výstrah (z %d)", len(result), len(alerts))
        return result

    def _poll_hydro(self) -> List[Alert]:
        hcfg = self.cfg.get("hydro") or {}
        if not hcfg.get("enabled", False):
            return []
        try:
            stations = hcfg.get("stations") or list(STATIONS.keys())
            if isinstance(stations, list):
                stations = [str(s) for s in stations]
            readings = fetch_hydro_readings(
                self.session,
                url=hcfg.get("url", "https://www.shmu.sk/sk/?page=765"),
                station_ids=stations,
            )
            min_spa = int(hcfg.get("min_spa", 1))
            alerts = readings_to_alerts(readings, min_spa=min_spa)
            log.info("HYDRO: SPA>=%s → %d objektov", min_spa, len(alerts))
            return alerts
        except Exception:
            log.exception("HYDRO: chyba pri načítaní")
            return []

    def _poll_lightning(self) -> List[Alert]:
        lcfg = self.cfg.get("lightning") or {}
        if not lcfg.get("enabled", False):
            return []
        try:
            pairs = fetch_lightning_alerts(lcfg)
            self._lightning_pos = {a.identifier: (lat, lon) for a, lat, lon in pairs}
            alerts = [a for a, _, _ in pairs]
            for a, lat, lon in pairs:
                log.info("  LGT %s @ [%.3f, %.3f]", a.headline, lat, lon)
            return alerts
        except Exception:
            log.exception("LIGHTNING: chyba")
            return []

    def _poll_alerts(self) -> List[Alert]:
        sources = self.cfg.get("sources", {})
        alerts: List[Alert] = []
        cap_url = sources.get("cap_base_url")
        if cap_url:
            try:
                alerts = fetch_cap_alerts(cap_url, self.session)
                log.info("CAP: načítaných %d výstrah", len(alerts))
            except Exception as e:
                log.exception("Chyba CAP: %s", e)
        if not alerts and sources.get("use_html_fallback", True):
            html_url = sources.get("html_url")
            if html_url:
                try:
                    regions_cfg = self.cfg.get("filter", {}).get("regions") or []
                    alerts = fetch_html_alerts(html_url, self.session, regions=regions_cfg)
                    log.info("HTML fallback: načítaných %d výstrah (pred filtrom)", len(alerts))
                except Exception as e:
                    log.exception("Chyba HTML fallback: %s", e)
        filtered = self._filter_alerts(alerts)
        filtered.extend(self._poll_hydro())
        filtered.extend(self._poll_lightning())
        return filtered

    def _beacon_needed(self) -> bool:
        interval = timedelta(minutes=self.cfg.get("beacon", {}).get("interval_minutes", 30))
        return datetime.now(timezone.utc) - self._last_beacon >= interval

    def _poll_needed(self) -> bool:
        interval = timedelta(seconds=self.cfg.get("beacon", {}).get("poll_interval_seconds", 300))
        return datetime.now(timezone.utc) - self._last_poll >= interval

    def _send_or_update(self, alerts: List[Alert]) -> None:
        now = datetime.now(timezone.utc)
        seen: Set[str] = set()
        lead = self._lead_hours()

        by_group: Dict[str, List[tuple]] = {}
        for alert in alerts:
            if alert.identifier.startswith("HYDRO-"):
                hp = resolve_hydro_position(alert)
                if not hp:
                    continue
                code, lat, lon = hp
                key = f"{alert.identifier}|{code}"
                by_group.setdefault(f"HYDRO-{alert.identifier}", []).append(
                    (key, alert, code, lat, lon)
                )
                continue
            if alert.identifier.startswith("LGT-"):
                pos = self._lightning_pos.get(alert.identifier)
                if not pos:
                    continue
                lat, lon = pos
                code = "LG"
                key = f"{alert.identifier}|LG"
                by_group.setdefault(f"LGT-{alert.identifier}", []).append(
                    (key, alert, code, lat, lon)
                )
                continue
            positions = resolve_alert_positions(alert.areas, alert.regions)
            if not positions:
                log.debug("Bez okresnej pozície: %s areas=%s", alert.event, alert.areas)
                continue
            for district_key, district_code, lat, lon in positions:
                key = f"{alert.identifier}|{district_key}"
                by_group.setdefault(district_key, []).append(
                    (key, alert, district_code, lat, lon)
                )

        prepared: List[Tuple[str, Alert, str, float, float, int, int]] = []
        for district_key, items in by_group.items():
            items.sort(key=lambda x: x[0])
            total = len(items)
            for slot, (key, alert, code, lat, lon) in enumerate(items):
                lat2, lon2 = offset_position(lat, lon, slot, total=total)
                prepared.append((key, alert, code, lat2, lon2, slot, total))

        if len(prepared) > 1:
            pts = [(p[3], p[4]) for p in prepared]
            pts2 = spread_collisions(pts)
            prepared = [
                (prepared[i][0], prepared[i][1], prepared[i][2], pts2[i][0], pts2[i][1],
                 prepared[i][5], prepared[i][6])
                for i in range(len(prepared))
            ]

        for key, alert, district_code, lat, lon, slot, total in prepared:
            seen.add(key)
            obj = self.active.get(key)
            obj_name = alert.object_name(district_code)
            pos_changed = False
            if obj is None:
                obj = ActiveObject(
                    alert=alert,
                    object_name=obj_name,
                    last_sent=datetime.min.replace(tzinfo=timezone.utc),
                    lat=lat,
                    lon=lon,
                    slot=slot,
                )
                self.active[key] = obj
                log.info(
                    "Nová výstraha: %s (%s) @ %s slot=%s/%s [%.4f, %.4f]",
                    alert.event, alert.level.color_sk, district_code, slot + 1, total, lat, lon,
                )
            else:
                if abs(obj.lat - lat) > 0.0005 or abs(obj.lon - lon) > 0.0005:
                    pos_changed = True
                    log.info(
                        "Posun ikony %s: [%.4f,%.4f] → [%.4f,%.4f] (slot %s/%s)",
                        obj_name.strip(), obj.lat, obj.lon, lat, lon, slot + 1, total,
                    )
            obj.alert = alert
            obj.object_name = obj_name
            obj.lat = lat
            obj.lon = lon
            obj.slot = slot
            # blesky častejšie – max 10 min medzi packetmi
            refresh = timedelta(minutes=10 if alert.identifier.startswith("LGT-") else 25)
            if (
                pos_changed
                or self._beacon_needed()
                or (now - obj.last_sent) > refresh
            ):
                if self.tx and self.tx.send_object(
                    alert, lat=lat, lon=lon, alive=True,
                    object_name=obj_name, district_label=district_code,
                ):
                    obj.last_sent = now
                    obj.kill_sent = False

        to_remove = []
        for key, obj in self.active.items():
            if key in seen and obj.alert.is_active(now, lead_hours=lead):
                continue
            if not obj.kill_sent:
                district_code = key.split("|")[-1][:3].upper() if "|" in key else "SK"
                log.info("Zrušujem objekt %s", obj.object_name)
                if self.tx:
                    self.tx.send_object(
                        obj.alert, lat=obj.lat, lon=obj.lon, alive=False,
                        object_name=obj.object_name, district_label=district_code,
                    )
                obj.kill_sent = True
            to_remove.append(key)
        for key in to_remove:
            del self.active[key]
        if self._beacon_needed():
            self._last_beacon = now
            if self.active and self.tx:
                n = len(self.active)
                max_lvl = max((o.alert.level for o in self.active.values()), default=AlertLevel.NONE)
                self.tx.send_status(f"SHMU alerts: {n} objects, max {max_lvl.color_sk}")

    def run(self) -> None:
        self._setup_logging()
        log.info("=== SHMÚ APRS Alerts service starting ===")
        aprs_cfg = self.cfg["aprs"]
        self.tx = AprsTransmitter(
            callsign=aprs_cfg["callsign"], passcode=aprs_cfg["passcode"],
            server=aprs_cfg.get("server", "euro.aprs2.net"),
            port=aprs_cfg.get("port", 14580),
            software=aprs_cfg.get("software", "SHMU"),
        )
        try:
            self.tx.connect()
        except Exception as e:
            log.error("Nepodarilo sa pripojiť k APRS-IS: %s", e)

        # blesky – spusti collector na pozadí
        lcfg = self.cfg.get("lightning") or {}
        if lcfg.get("enabled", False):
            try:
                get_collector(lcfg)
            except Exception:
                log.exception("LIGHTNING: collector sa nespustil")

        self._running = True
        self._notify("READY=1")

        def _handle_signal(signum, frame):
            log.info("Prijatý signál %s – ukončujem", signum)
            self._running = False

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        log.info(
            "Služba beží. okresy + hydro=%s lightning=%s",
            self.cfg.get("hydro", {}).get("enabled", False),
            lcfg.get("enabled", False),
        )
        while self._running:
            try:
                if self._poll_needed():
                    alerts = self._poll_alerts()
                    self._last_poll = datetime.now(timezone.utc)
                    self._send_or_update(alerts)
                if self.watchdog_enabled and self._notify_socket:
                    if time.monotonic() - self._last_watchdog >= self.watchdog_interval:
                        self._notify("WATCHDOG=1")
                        self._last_watchdog = time.monotonic()
            except Exception:
                log.exception("Neočekávaná chyba v hlavnej slučke")
            time.sleep(5)
        log.info("Ukončujem – ruším aktívne objekty…")
        self._notify("STOPPING=1")
        for key, obj in list(self.active.items()):
            if obj.kill_sent or not self.tx:
                continue
            self.tx.send_object(
                obj.alert, lat=obj.lat, lon=obj.lon, alive=False,
                object_name=obj.object_name, district_label="SK",
            )
        if self.tx:
            self.tx.disconnect()
        log.info("Služba ukončená")
