"""Hlavná logika služby – sťahovanie, filtrovanie, vysielanie, expirácia."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
import yaml

from .aprs_tx import AprsTransmitter
from .cap_parser import fetch_cap_alerts
from .html_fallback import fetch_html_alerts
from .districts import resolve_alert_positions
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

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _setup_logging(self) -> None:
        level = getattr(logging, self.cfg.get("logging", {}).get("level", "INFO").upper())
        log_file = self.cfg.get("logging", {}).get("file")
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if log_file:
            try:
                from logging.handlers import RotatingFileHandler
                handlers.append(RotatingFileHandler(
                    log_file,
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
        """Hodiny pred effective, kedy už začať vysielať výstrahu."""
        return float(self.cfg.get("beacon", {}).get("lead_hours", 12))

    def _filter_alerts(self, alerts: List[Alert]) -> List[Alert]:
        flt = self.cfg.get("filter", {})
        regions = set(r.upper() for r in flt.get("regions", []))
        districts = [d.lower() for d in flt.get("districts", [])]
        min_level = AlertLevel(flt.get("min_level", 1))
        lead = self._lead_hours()
        result = []
        for a in alerts:
            if a.level < min_level:
                continue
            if not a.is_active(lead_hours=lead):
                continue
            if not regions and not districts:
                result.append(a)
                continue
            match_region = bool(regions & set(r.upper() for r in a.regions))
            match_district = False
            if districts:
                for area in a.areas:
                    low = area.lower()
                    if any(d in low for d in districts):
                        match_district = True
                        break
            if match_region or match_district:
                result.append(a)
            elif not a.regions and not a.areas:
                result.append(a)
        return result

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
                    alerts = fetch_html_alerts(html_url, self.session)
                except Exception as e:
                    log.exception("Chyba HTML fallback: %s", e)
        return self._filter_alerts(alerts)

    def _beacon_needed(self) -> bool:
        interval = timedelta(minutes=self.cfg.get("beacon", {}).get("interval_minutes", 30))
        return datetime.now(timezone.utc) - self._last_beacon >= interval

    def _poll_needed(self) -> bool:
        interval = timedelta(seconds=self.cfg.get("beacon", {}).get("poll_interval_seconds", 300))
        return datetime.now(timezone.utc) - self._last_poll >= interval

    def _send_or_update(self, alerts: List[Alert]) -> None:
        """Jeden APRS objekt do stredu každého okresu, na ktorý sa výstraha vzťahuje."""
        now = datetime.now(timezone.utc)
        seen: Set[str] = set()
        lead = self._lead_hours()

        for alert in alerts:
            positions = resolve_alert_positions(alert.areas, alert.regions)
            for district_code, lat, lon in positions:
                key = f"{alert.identifier}|{district_code}"
                seen.add(key)
                obj = self.active.get(key)
                obj_name = alert.object_name(district_code)

                if obj is None:
                    obj = ActiveObject(
                        alert=alert,
                        object_name=obj_name,
                        last_sent=datetime.min.replace(tzinfo=timezone.utc),
                    )
                    self.active[key] = obj
                    log.info(
                        "Nová výstraha: %s (%s) @ %s [%.3f, %.3f]",
                        alert.event, alert.level.color_sk, district_code, lat, lon,
                    )

                obj.alert = alert
                obj.object_name = obj_name

                if self._beacon_needed() or (now - obj.last_sent) > timedelta(minutes=25):
                    if self.tx and self.tx.send_object(
                        alert,
                        lat=lat,
                        lon=lon,
                        alive=True,
                        object_name=obj_name,
                        district_label=district_code,
                    ):
                        obj.last_sent = now
                        obj.kill_sent = False

        to_remove = []
        for key, obj in self.active.items():
            if key in seen and obj.alert.is_active(now, lead_hours=lead):
                continue
            if not obj.kill_sent:
                district_code = key.split("|", 1)[-1] if "|" in key else "SK"
                positions = resolve_alert_positions(obj.alert.areas, obj.alert.regions)
                lat, lon = 48.67, 19.70
                for code, la, lo in positions:
                    if code == district_code:
                        lat, lon = la, lo
                        break
                else:
                    if positions:
                        lat, lon = positions[0][1], positions[0][2]
                log.info("Zrušujem objekt %s (expirácia/odstránenie)", obj.object_name)
                if self.tx:
                    self.tx.send_object(
                        obj.alert,
                        lat=lat,
                        lon=lon,
                        alive=False,
                        object_name=obj.object_name,
                        district_label=district_code,
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
            callsign=aprs_cfg["callsign"],
            passcode=aprs_cfg["passcode"],
            server=aprs_cfg.get("server", "euro.aprs2.net"),
            port=aprs_cfg.get("port", 14580),
            software=aprs_cfg.get("software", "SHMU"),
        )
        try:
            self.tx.connect()
        except Exception as e:
            log.error("Nepodarilo sa pripojiť k APRS-IS: %s", e)

        self._running = True
        self._notify("READY=1")

        def _handle_signal(signum, frame):
            log.info("Prijatý signál %s – ukončujem", signum)
            self._running = False

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        log.info(
            "Služba beží. Filter: regions=%s districts=%s min_level=%s lead_hours=%s",
            self.cfg.get("filter", {}).get("regions"),
            self.cfg.get("filter", {}).get("districts"),
            self.cfg.get("filter", {}).get("min_level"),
            self._lead_hours(),
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
            district_code = key.split("|", 1)[-1] if "|" in key else "SK"
            positions = resolve_alert_positions(obj.alert.areas, obj.alert.regions)
            lat, lon = 48.67, 19.70
            for code, la, lo in positions:
                if code == district_code:
                    lat, lon = la, lo
                    break
            else:
                if positions:
                    lat, lon = positions[0][1], positions[0][2]
            self.tx.send_object(
                obj.alert,
                lat=lat,
                lon=lon,
                alive=False,
                object_name=obj.object_name,
                district_label=district_code,
            )
        if self.tx:
            self.tx.disconnect()
        log.info("Služba ukončená")
