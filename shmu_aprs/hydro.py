"""SHMÚ vodomerné stanice – vodný stav a stupeň povodňovej aktivity (SPA)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

DEFAULT_URL = "https://www.shmu.sk/sk/?page=765"

# Vybrané stanice (KSK/PSK/ZSK/BBSK) – súradnice približné, prahy SPA v cm (ak známe)
# Prahy: (1. st., 2. st., 3. st.) – podľa SHMÚ detailu stanice, kde je známe
STATIONS: Dict[str, dict] = {
    # --- Hornád / Poprad / Torysa (východ) ---
    "8705": {"name": "Košice", "river": "Hornád", "lat": 48.7200, "lon": 21.2580, "spa": (200, 300, 400)},
    "8690": {"name": "Kysak", "river": "Hornád", "lat": 48.8520, "lon": 21.2000, "spa": (200, 300, 400)},
    "8510": {"name": "Margecany", "river": "Hornád", "lat": 48.8450, "lon": 21.0150, "spa": (250, 350, 450)},
    "8000": {"name": "Svit", "river": "Poprad", "lat": 49.0600, "lon": 20.2060, "spa": (200, 350, 450)},
    "8065": {"name": "Poprad-Matejovce", "river": "Poprad", "lat": 49.0800, "lon": 20.3100, "spa": (180, 280, 380)},
    "8780": {"name": "Prešov", "river": "Torysa", "lat": 48.9980, "lon": 21.2400, "spa": (180, 280, 380)},
    "8840": {"name": "Prešov", "river": "Sekčov", "lat": 49.0100, "lon": 21.2600, "spa": (120, 200, 280)},
    "9230": {"name": "Humenné", "river": "Laborec", "lat": 48.9370, "lon": 21.9100, "spa": (200, 300, 400)},
    "9240": {"name": "Michalovce", "river": "Laborec", "lat": 48.7560, "lon": 21.9200, "spa": (200, 300, 400)},
    "9450": {"name": "Bardejov", "river": "Topľa", "lat": 49.2910, "lon": 21.2730, "spa": (150, 250, 350)},
    "7690": {"name": "Rožňava", "river": "Slaná", "lat": 48.6600, "lon": 20.5330, "spa": (150, 250, 350)},
    # --- Váh / Orava / Kysuca (sever) ---
    "5550": {"name": "Liptovský Mikuláš", "river": "Váh", "lat": 49.0840, "lon": 19.6120, "spa": (180, 280, 380)},
    "5840": {"name": "Trstená", "river": "Oravica", "lat": 49.3610, "lon": 19.6120, "spa": (150, 250, 350)},
    "5848": {"name": "Oravský Podzámok", "river": "Orava", "lat": 49.2600, "lon": 19.3600, "spa": (200, 300, 400)},
    "6130": {"name": "Martin", "river": "Turiec", "lat": 49.0660, "lon": 18.9220, "spa": (150, 250, 350)},
    "6180": {"name": "Čadca", "river": "Kysuca", "lat": 49.4390, "lon": 18.7870, "spa": (150, 250, 350)},
    "6340": {"name": "Žilina", "river": "Rajčanka", "lat": 49.2230, "lon": 18.7390, "spa": (120, 200, 280)},
    # --- Hron (stred) ---
    "7015": {"name": "Brezno", "river": "Hron", "lat": 48.8040, "lon": 19.6440, "spa": (150, 250, 350)},
    "7160": {"name": "Banská Bystrica", "river": "Hron", "lat": 48.7360, "lon": 19.1460, "spa": (200, 300, 400)},
    "7179": {"name": "Zvolen", "river": "Hron", "lat": 48.5740, "lon": 19.1530, "spa": (200, 300, 400)},
}


@dataclass
class HydroReading:
    station_id: str
    name: str
    river: str
    level_cm: int
    spa: int  # 0–3
    measured_at: Optional[datetime]
    lat: float
    lon: float
    spa_from_icon: bool = False

    def to_alert(self) -> Alert:
        """Alert bez pevnej expirácie – na mape kým SPA trvá (riadi poll)."""
        now = datetime.now(timezone.utc)
        level = AlertLevel(min(max(self.spa, 1), 3))
        event = f"SPA {self.spa}.st. {self.river}"
        return Alert(
            identifier=f"HYDRO-{self.station_id}",
            event=event,
            level=level,
            headline=f"{self.name} – {self.river}: {self.level_cm} cm",
            description=f"Vodný stav {self.level_cm} cm, SPA {self.spa}. st. (kým trvá stav)",
            areas=[self.name],
            regions=[],
            effective=now - timedelta(minutes=5),
            expires=None,  # trvanie = kým je SPA v dátach; kill po poklese
            source="SHMU-HYDRO",
        )


def _parse_time(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _spa_from_level(level_cm: int, thresholds: Tuple[int, int, int]) -> int:
    s1, s2, s3 = thresholds
    if level_cm >= s3:
        return 3
    if level_cm >= s2:
        return 2
    if level_cm >= s1:
        return 1
    return 0


def _spa_from_row_images(tr) -> int:
    spa = 0
    for img in tr.find_all("img"):
        src = img.get("src") or ""
        if "3st.gif" in src:
            spa = max(spa, 3)
        elif "2st.gif" in src:
            spa = max(spa, 2)
        elif "1st.gif" in src:
            spa = max(spa, 1)
    return spa


def fetch_hydro_readings(
    session: Optional[requests.Session] = None,
    url: str = DEFAULT_URL,
    station_ids: Optional[List[str]] = None,
) -> List[HydroReading]:
    """Načíta aktuálne vodné stavy a vypočíta SPA pre vybrané stanice."""
    sess = session or requests.Session()
    headers = {"User-Agent": "shmu-aprs-alerts/1.0 (ham radio; hydro)"}
    log.info("HYDRO: sťahujem %s", url)
    r = sess.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    want = set(station_ids) if station_ids else set(STATIONS.keys())
    found: Dict[str, HydroReading] = {}

    for a in soup.find_all("a", href=True):
        m = re.search(r"station_id=(\d+)", a["href"])
        if not m:
            continue
        sid = m.group(1)
        if sid not in want:
            continue
        tr = a.find_parent("tr")
        if not tr:
            continue
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        name = a.get_text(strip=True)
        river = tds[2].get_text(strip=True)
        time_s = tds[3].get_text(strip=True)
        level = None
        for td in tds:
            t = td.get_text(strip=True)
            if re.fullmatch(r"-?\d+", t):
                level = int(t)
                break
        if level is None:
            continue

        meta = STATIONS.get(sid, {})
        lat = float(meta.get("lat", 48.67))
        lon = float(meta.get("lon", 19.70))
        if meta.get("name"):
            name = meta["name"]
        if meta.get("river"):
            river = meta["river"]

        spa_icon = _spa_from_row_images(tr)
        spa_thr = 0
        if "spa" in meta:
            spa_thr = _spa_from_level(level, meta["spa"])
        spa = max(spa_icon, spa_thr)

        found[sid] = HydroReading(
            station_id=sid,
            name=name,
            river=river,
            level_cm=level,
            spa=spa,
            measured_at=_parse_time(time_s),
            lat=lat,
            lon=lon,
            spa_from_icon=spa_icon > 0,
        )

    log.info("HYDRO: načítaných %d staníc (SPA>0: %d)",
             len(found), sum(1 for x in found.values() if x.spa > 0))
    return list(found.values())


def readings_to_alerts(
    readings: List[HydroReading],
    min_spa: int = 1,
    lifetime_hours: float = 0.0,  # ignorované – trvanie = trvanie SPA stavu
) -> List[Alert]:
    """Iba stanice so SPA >= min_spa. Objekt žije kým stav trvá."""
    out: List[Alert] = []
    for rd in readings:
        if rd.spa < min_spa:
            continue
        out.append(rd.to_alert())
    return out


def resolve_hydro_position(alert: Alert) -> Optional[Tuple[str, float, float]]:
    """Vráti (short_code, lat, lon) pre HYDRO alert."""
    if not alert.identifier.startswith("HYDRO-"):
        return None
    sid = alert.identifier.replace("HYDRO-", "", 1)
    meta = STATIONS.get(sid)
    if not meta:
        return None
    code = (meta.get("name") or sid)[:3].upper()
    return code, float(meta["lat"]), float(meta["lon"])
