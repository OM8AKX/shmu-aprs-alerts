"""Odosielanie APRS objektov a bulletinov cez APRS-IS."""

from __future__ import annotations

import logging
import socket
import time
from datetime import datetime, timezone
from typing import Optional

import aprslib

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)


def _deg_to_aprs(lat: float, lon: float) -> tuple[str, str]:
    def conv(val: float, is_lat: bool) -> str:
        hem = "N" if (val >= 0 and is_lat) else ("S" if is_lat else ("E" if val >= 0 else "W"))
        val = abs(val)
        deg = int(val)
        minutes = (val - deg) * 60
        if is_lat:
            return f"{deg:02d}{minutes:05.2f}{hem}"
        return f"{deg:03d}{minutes:05.2f}{hem}"
    return conv(lat, True), conv(lon, False)


class AprsTransmitter:
    def __init__(self, callsign: str, passcode: int | str, server: str = "euro.aprs2.net", port: int = 14580, software: str = "SHMU"):
        self.callsign = callsign.upper()
        self.passcode = str(passcode)
        self.server = server
        self.port = port
        self.software = software[:4]
        self._ais: Optional[aprslib.IS] = None

    def connect(self) -> None:
        log.info("Pripájam sa na APRS-IS %s:%d ako %s", self.server, self.port, self.callsign)
        self._ais = aprslib.IS(self.callsign, passwd=self.passcode, host=self.server, port=self.port)
        self._ais.connect(blocking=True)
        log.info("Pripojené k APRS-IS")

    def disconnect(self) -> None:
        if self._ais:
            try:
                self._ais.close()
            except Exception:
                pass
            self._ais = None

    def _send(self, packet: str) -> bool:
        if not self._ais:
            self.connect()
        try:
            self._ais.sendall(packet)
            log.debug("TX: %s", packet)
            return True
        except (socket.error, OSError, aprslib.ConnectionDrop, aprslib.ConnectionError) as e:
            log.error("Chyba pri odosielaní: %s – skúšam reconnect", e)
            self.disconnect()
            time.sleep(2)
            try:
                self.connect()
                self._ais.sendall(packet)
                return True
            except Exception as e2:
                log.error("Reconnect zlyhal: %s", e2)
                return False

    def send_object(
        self,
        alert: Alert,
        lat: float = 48.736,
        lon: float = 21.258,
        alive: bool = True,
        object_name: str | None = None,
        district_label: str = "",
    ) -> bool:
        """Pošle APRS Object Report. lat/lon = stred okresu."""
        name = object_name or alert.object_name(district_label)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%d%H%M") + "z"
        lat_s, lon_s = _deg_to_aprs(lat, lon)
        symbol_table, symbol_code = alert.aprs_symbol()
        live_char = "_" if not alive else "*"
        comment = alert.short_comment(40)
        if district_label:
            color = alert.level.color_sk.upper()
            comment = f"{color} {alert.event} {district_label}"[:40]
        if alert.level == AlertLevel.RED:
            comment = "!!! " + comment
        elif alert.level == AlertLevel.ORANGE:
            comment = "!! " + comment
        obj_name = name.ljust(9)[:9]
        info = f";{obj_name}{live_char}{ts}{lat_s}{symbol_table}{lon_s}{symbol_code}{comment}"
        packet = f"{self.callsign}>AP{self.software},TCPIP*:{info}"
        ok = self._send(packet)
        if ok:
            log.info("Objekt %s %s (%s)", obj_name.strip(), "LIVE" if alive else "KILL", comment)
        return ok

    def send_bulletin(self, text: str, bulletin_id: str = "1") -> bool:
        bid = bulletin_id.ljust(1)[:1]
        dest = f"BLN{bid}"
        msg = text[:67]
        packet = f"{self.callsign}>AP{self.software},TCPIP*::{dest.ljust(9)}:{msg}"
        ok = self._send(packet)
        if ok:
            log.info("Bulletin: %s", msg)
        return ok

    def send_status(self, text: str) -> bool:
        packet = f"{self.callsign}>AP{self.software},TCPIP*:>{text[:62]}"
        return self._send(packet)
