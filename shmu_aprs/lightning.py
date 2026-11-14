"""Aktivita bleskov – agregácia pre APRS (SK + 30 km).

Zdroj: Blitzortung.org live websocket (nekomerčné / hobby použitie).
Údery sa zoskupia (aby sa nezahltil APRS-IS), ikona však ide na
skutočnú polohu – centroid úderov v klastri, resp. posledný úder.

Test bez reálnej búrky:
  lightning:
    enabled: true
    simulate: true
"""

from __future__ import annotations

import json
import logging
import math
import random
import ssl
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

DEFAULT_SOUTH = 47.48
DEFAULT_WEST = 16.50
DEFAULT_NORTH = 49.92
DEFAULT_EAST = 22.90

# ws7 má často certifikat s hostname mismatch – radšej ws1/ws8
WS_SERVERS = (
    "wss://ws1.blitzortung.org/",
    "wss://ws8.blitzortung.org/",
    "wss://ws6.blitzortung.org/",
)

_SIM_FOCI = (
    (48.72, 21.26),
    (49.00, 21.24),
    (49.06, 20.30),
    (48.15, 17.11),
)


@dataclass
class Strike:
    lat: float
    lon: float
    ts: float


@dataclass
class CellActivity:
    lat: float
    lon: float
    count: int
    last_ts: float
    cell_id: str


def _in_bbox(lat: float, lon: float, south: float, west: float, north: float, east: float) -> bool:
    return south <= lat <= north and west <= lon <= east


def _cell_key(lat: float, lon: float, grid: float) -> Tuple[int, int]:
    return int(math.floor(lat / grid)), int(math.floor(lon / grid))


def _sslopt() -> dict:
    """Blitzortung certs často nezodpovedajú hostname – overenie vypnuté."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {"context": ctx}


class LightningCollector:
    def __init__(
        self,
        south: float = DEFAULT_SOUTH,
        west: float = DEFAULT_WEST,
        north: float = DEFAULT_NORTH,
        east: float = DEFAULT_EAST,
        grid_deg: float = 0.20,
        window_seconds: int = 900,
        simulate: bool = False,
        position_mode: str = "last",
    ):
        self.south = south
        self.west = west
        self.north = north
        self.east = east
        self.grid_deg = grid_deg
        self.window_seconds = window_seconds
        self.simulate = simulate
        self.position_mode = (position_mode or "last").lower()
        self._strikes: List[Strike] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        target = self._run_simulate if self.simulate else self._run
        self._thread = threading.Thread(target=target, name="lightning-ws", daemon=True)
        self._thread.start()
        mode = "SIMULATE" if self.simulate else "live"
        log.info(
            "LIGHTNING: collector štart [%s] pos=%s (bbox %.2f–%.2f / %.2f–%.2f, grid=%.2f°)",
            mode, self.position_mode, self.south, self.north, self.west, self.east, self.grid_deg,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def inject_simulate(self, n_per_focus: int = 8) -> None:
        now = time.time()
        for lat0, lon0 in _SIM_FOCI:
            for _ in range(n_per_focus):
                lat = lat0 + random.uniform(-0.03, 0.03)
                lon = lon0 + random.uniform(-0.04, 0.04)
                ts = now - random.uniform(0, min(180, self.window_seconds * 0.3))
                self._add(lat, lon, ts)
        log.info("LIGHTNING: simulate inject – %d ohnisk × %d úderov", len(_SIM_FOCI), n_per_focus)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._strikes = [s for s in self._strikes if s.ts >= cutoff]

    def _add(self, lat: float, lon: float, ts: float) -> None:
        if not _in_bbox(lat, lon, self.south, self.west, self.north, self.east):
            return
        with self._lock:
            self._strikes.append(Strike(lat=lat, lon=lon, ts=ts))
            self._prune(ts)

    def get_cells(self, max_cells: int = 15) -> List[CellActivity]:
        now = time.time()
        with self._lock:
            self._prune(now)
            strikes = list(self._strikes)

        buckets: Dict[Tuple[int, int], List[Strike]] = defaultdict(list)
        for s in strikes:
            buckets[_cell_key(s.lat, s.lon, self.grid_deg)].append(s)

        cells: List[CellActivity] = []
        for (i, j), items in buckets.items():
            last = max(items, key=lambda x: x.ts)
            if self.position_mode == "centroid":
                lat = sum(x.lat for x in items) / len(items)
                lon = sum(x.lon for x in items) / len(items)
            else:
                lat, lon = last.lat, last.lon
            cells.append(CellActivity(
                lat=lat,
                lon=lon,
                count=len(items),
                last_ts=last.ts,
                cell_id=f"{i}_{j}",
            ))
        cells.sort(key=lambda c: (c.count, c.last_ts), reverse=True)
        return cells[:max_cells]

    def _parse_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            pos = data.get("pos") or data.get("p")
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                lat, lon = pos[0], pos[1]
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return
        ts = data.get("time") or data.get("t") or data.get("ts")
        try:
            ts_f = float(ts)
            if ts_f > 1e12:
                ts_f /= 1e9
            elif ts_f > 1e10:
                ts_f /= 1e3
        except (TypeError, ValueError):
            ts_f = time.time()
        self._add(lat_f, lon_f, ts_f)

    def _run_simulate(self) -> None:
        log.warning("LIGHTNING: SIMULATE režim – fiktívne blesky (vypni simulate: false po teste)")
        while not self._stop.is_set():
            self.inject_simulate(n_per_focus=6)
            self._stop.wait(20.0)

    def _run(self) -> None:
        try:
            import websocket  # websocket-client
        except ImportError:
            log.error("LIGHTNING: chýba balík websocket-client (pip install websocket-client)")
            return

        backoff = 3.0
        while not self._stop.is_set():
            url = random.choice(WS_SERVERS)
            try:
                log.info("LIGHTNING: pripájam %s", url)
                ws = websocket.create_connection(
                    url,
                    timeout=25,
                    enable_multithread=True,
                    sslopt=_sslopt(),
                )
                # subscribe (kompatibilita s map klientmi Blitzortung)
                ws.send(json.dumps({"a": 542}))
                self._connected = True
                log.info("LIGHTNING: pripojené %s", url)
                backoff = 3.0
                ws.settimeout(45)
                idle = 0
                while not self._stop.is_set():
                    try:
                        msg = ws.recv()
                    except Exception:
                        idle += 1
                        if idle > 3:
                            break
                        continue
                    idle = 0
                    if not msg:
                        break
                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", errors="ignore")
                    self._parse_message(msg)
                try:
                    ws.close()
                except Exception:
                    pass
                self._connected = False
            except Exception as e:
                self._connected = False
                log.warning("LIGHTNING: spojenie zlyhalo: %s – retry %.0fs", e, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 60.0)


_collector: Optional[LightningCollector] = None


def get_collector(cfg: Optional[dict] = None) -> LightningCollector:
    global _collector
    cfg = cfg or {}
    if _collector is None:
        _collector = LightningCollector(
            south=float(cfg.get("south", DEFAULT_SOUTH)),
            west=float(cfg.get("west", DEFAULT_WEST)),
            north=float(cfg.get("north", DEFAULT_NORTH)),
            east=float(cfg.get("east", DEFAULT_EAST)),
            grid_deg=float(cfg.get("grid_deg", 0.20)),
            window_seconds=int(cfg.get("window_minutes", 15)) * 60,
            simulate=bool(cfg.get("simulate", False)),
            position_mode=str(cfg.get("position_mode", "last")),
        )
        _collector.start()
    return _collector


def cells_to_alerts(
    cells: List[CellActivity],
    window_minutes: int = 15,
) -> List[Alert]:
    now = datetime.now(timezone.utc)
    out: List[Alert] = []
    for c in cells:
        age_min = max(0, int((time.time() - c.last_ts) / 60))
        event = "Blesky"
        if c.count >= 40:
            level = AlertLevel.RED
        elif c.count >= 15:
            level = AlertLevel.ORANGE
        else:
            level = AlertLevel.YELLOW
        identifier = f"LGT-{c.cell_id}"
        headline = f"Blesky {c.count}/{window_minutes}min"
        desc = (
            f"Aktivita bleskov: {c.count} úderov / {window_minutes} min, "
            f"posledný pred {age_min} min @ {c.lat:.4f},{c.lon:.4f}"
        )
        out.append(Alert(
            identifier=identifier,
            event=event,
            level=level,
            headline=headline,
            description=desc,
            areas=[f"LGT {c.cell_id}"],
            regions=[],
            effective=now - timedelta(minutes=5),
            expires=None,
            source="LIGHTNING",
        ))
    return out


def resolve_lightning_position(alert: Alert) -> Optional[Tuple[str, float, float]]:
    if not alert.identifier.startswith("LGT-"):
        return None
    return None


def fetch_lightning_alerts(cfg: dict) -> List[Tuple[Alert, float, float]]:
    if not cfg.get("enabled", False):
        return []
    collector = get_collector(cfg)
    if cfg.get("simulate") and not collector.get_cells(max_cells=1):
        collector.inject_simulate()
        time.sleep(0.2)
    max_cells = int(cfg.get("max_objects", 15))
    window = int(cfg.get("window_minutes", 15))
    cells = collector.get_cells(max_cells=max_cells)
    min_count = int(cfg.get("min_strikes", 2))
    cells = [c for c in cells if c.count >= min_count]
    alerts = cells_to_alerts(cells, window_minutes=window)
    out: List[Tuple[Alert, float, float]] = []
    for a, c in zip(alerts, cells):
        out.append((a, c.lat, c.lon))
    log.info(
        "LIGHTNING: %d aktívnych buniek (min_strikes=%s simulate=%s pos=%s)",
        len(out), min_count, bool(cfg.get("simulate")),
        cfg.get("position_mode", "last"),
    )
    return out
