"""Aktivita bleskov – agregácia pre APRS (SK + 30 km).

Zdroj: Blitzortung.org live websocket (nekomerčné / hobby použitie).
Každý úder sa NEPOŠLE – len stredy mriežky s počtom úderov,
aby sa nezahltil APRS-IS.
"""

from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

# Slovensko + ~30 km za hranicami (približný bbox)
DEFAULT_SOUTH = 47.48
DEFAULT_WEST = 16.50
DEFAULT_NORTH = 49.92
DEFAULT_EAST = 22.90

WS_SERVERS = (
    "wss://ws1.blitzortung.org/",
    "wss://ws7.blitzortung.org/",
    "wss://ws8.blitzortung.org/",
)


@dataclass
class Strike:
    lat: float
    lon: float
    ts: float  # unix seconds


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


def _cell_center(i: int, j: int, grid: float) -> Tuple[float, float]:
    return (i + 0.5) * grid, (j + 0.5) * grid


class LightningCollector:
    """Zbiera údery na pozadí a agreguje do mriežky."""

    def __init__(
        self,
        south: float = DEFAULT_SOUTH,
        west: float = DEFAULT_WEST,
        north: float = DEFAULT_NORTH,
        east: float = DEFAULT_EAST,
        grid_deg: float = 0.20,
        window_seconds: int = 900,
    ):
        self.south = south
        self.west = west
        self.north = north
        self.east = east
        self.grid_deg = grid_deg
        self.window_seconds = window_seconds
        self._strikes: List[Strike] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lightning-ws", daemon=True)
        self._thread.start()
        log.info(
            "LIGHTNING: collector štart (bbox %.2f–%.2f / %.2f–%.2f, grid=%.2f°)",
            self.south, self.north, self.west, self.east, self.grid_deg,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

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
            clat, clon = _cell_center(i, j, self.grid_deg)
            last_ts = max(x.ts for x in items)
            cells.append(CellActivity(
                lat=clat,
                lon=clon,
                count=len(items),
                last_ts=last_ts,
                cell_id=f"{i}_{j}",
            ))
        # najaktívnejšie / najnovšie prvé
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
            # niektoré formáty: pos / time
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
            # nanosekundy → sekundy
            if ts_f > 1e12:
                ts_f /= 1e9
            elif ts_f > 1e10:
                ts_f /= 1e3
        except (TypeError, ValueError):
            ts_f = time.time()
        self._add(lat_f, lon_f, ts_f)

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
                ws = websocket.create_connection(url, timeout=20, enable_multithread=True)
                # handshake – region / subscribe (kompatibilita s map klientmi)
                ws.send(json.dumps({"a": 542}))
                self._connected = True
                backoff = 3.0
                ws.settimeout(30)
                while not self._stop.is_set():
                    try:
                        msg = ws.recv()
                    except Exception:
                        break
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
        )
        _collector.start()
    return _collector


def cells_to_alerts(
    cells: List[CellActivity],
    window_minutes: int = 15,
) -> List[Alert]:
    """Každá aktívna bunka → jeden APRS alert (bez pevnej expirácie = kým je aktivita)."""
    now = datetime.now(timezone.utc)
    out: List[Alert] = []
    for c in cells:
        age_min = max(0, int((time.time() - c.last_ts) / 60))
        event = "Blesky"
        # intenzita podľa počtu v okne
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
            f"posledný pred {age_min} min (Blitzortung)"
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
            expires=None,  # trvá kým bunka ostane aktívna v collectore
            source="LIGHTNING",
        ))
    return out


def resolve_lightning_position(alert: Alert) -> Optional[Tuple[str, float, float]]:
    if not alert.identifier.startswith("LGT-"):
        return None
    cell_id = alert.identifier[4:]
    # lat/lon nie sú v identifier – treba ich z aktuálnych buniek
    # service predá lat/lon priamo z CellActivity
    return None


def fetch_lightning_alerts(cfg: dict) -> List[Tuple[Alert, float, float]]:
    """Vráti zoznam (alert, lat, lon) pre aktívne bunky."""
    if not cfg.get("enabled", False):
        return []
    collector = get_collector(cfg)
    max_cells = int(cfg.get("max_objects", 15))
    window = int(cfg.get("window_minutes", 15))
    cells = collector.get_cells(max_cells=max_cells)
    min_count = int(cfg.get("min_strikes", 2))
    cells = [c for c in cells if c.count >= min_count]
    alerts = cells_to_alerts(cells, window_minutes=window)
    # spáruj podľa poradia
    out: List[Tuple[Alert, float, float]] = []
    for a, c in zip(alerts, cells):
        out.append((a, c.lat, c.lon))
    log.info("LIGHTNING: %d aktívnych buniek (min_strikes=%s)", len(out), min_count)
    return out
