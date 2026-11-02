"""Parser HTML tabuľky výstrah SHMÚ podľa okresov (page=987)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from urllib.parse import quote

import requests
from lxml import html

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

DEFAULT_DETAIL_URL = (
    "https://www.shmu.sk/sk/?page=987&id=&d=0&jav=&roll=KSK%7CPSK"
)

_KRAJ_RE = re.compile(
    r"(kraj|bratislavský|banskobystrický|trenčiansky|košický|"
    r"nitriansky|trnavský|prešovský|žilinský)",
    re.I,
)


def _max_level_from_cells(cells: list) -> int:
    levels = []
    for c in cells:
        t = (c or "").strip()
        if t.isdigit():
            v = int(t)
            if 0 <= v <= 3:
                levels.append(v)
    return max(levels) if levels else 0


def _is_kraj_row(name: str) -> bool:
    n = name.strip()
    if not n:
        return True
    if n.startswith("**") and n.endswith("**"):
        return True
    return bool(_KRAJ_RE.search(n)) and "mesto" not in n.lower() and "okolie" not in n.lower()


def _normalize_district(name: str) -> str:
    return " ".join(name.replace("**", "").split())


def fetch_html_alerts(
    url: str,
    session: Optional[requests.Session] = None,
    regions: Optional[List[str]] = None,
) -> List[Alert]:
    """Jedna Alert pre každý okres so stupňom ≥ 1 z tabuľky SHMÚ."""
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "SHMU-APRS-Alerts/1.1 (Amateur Radio)",
        "Accept-Language": "sk,en;q=0.8",
    })

    fetch_url = url or DEFAULT_DETAIL_URL
    if "page=987" in fetch_url and "roll=" not in fetch_url and regions:
        roll = quote("|".join(r.upper() for r in regions), safe="|")
        sep = "&" if "?" in fetch_url else "?"
        fetch_url = f"{fetch_url}{sep}roll={roll}"
    elif "page=987" not in fetch_url:
        if regions:
            roll = quote("|".join(r.upper() for r in regions), safe="|")
            fetch_url = f"https://www.shmu.sk/sk/?page=987&id=&d=0&jav=&roll={roll}"
        else:
            fetch_url = DEFAULT_DETAIL_URL

    try:
        r = session.get(fetch_url, timeout=45)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("HTML okresný parser zlyhal: %s", e)
        return []

    tree = html.fromstring(r.content)
    now = datetime.now(timezone.utc)
    alerts: List[Alert] = []

    page_text = tree.text_content()
    headline_level = AlertLevel.NONE
    m = re.search(r"vydal.*?výstrahy.*?(\d)\.\s*stup", page_text, re.I)
    if m:
        headline_level = AlertLevel(int(m.group(1)))

    for table in tree.xpath("//table"):
        for tr in table.xpath(".//tr"):
            cells = ["".join(td.itertext()).strip() for td in tr.xpath("./td|./th")]
            if len(cells) < 3:
                continue
            name = ""
            for c in cells[:3]:
                if c and not c.isdigit() and c not in ("Región", "Jav", "0"):
                    name = c
                    break
            if not name or _is_kraj_row(name):
                continue
            district = _normalize_district(name)
            level_num = _max_level_from_cells(cells)
            if level_num < 1:
                continue
            level = AlertLevel(level_num)
            safe = re.sub(r"[^A-Za-z0-9]", "", district)[:12] or "OKR"
            identifier = f"HTML-{now.strftime('%Y%m%d')}-{safe}"
            alerts.append(Alert(
                identifier=identifier,
                event="Výstraha",
                level=level,
                headline=f"SHMÚ {level.color_sk} – {district}",
                description=f"Výstraha {level.value}. stupňa pre okres {district}",
                areas=[district],
                regions=[],
                effective=now - timedelta(hours=1),
                expires=now + timedelta(hours=12),
                sent=now,
                source="HTML",
            ))
            log.info("HTML: okres %s → stupeň %s", district, level.color_sk)

    if not alerts and headline_level != AlertLevel.NONE:
        log.warning(
            "HTML tabuľka bez okresov so stupňom ≥ 1 (nadpis: %s) – nič nevysielam",
            headline_level.color_sk,
        )

    by_area: dict[str, Alert] = {}
    for a in alerts:
        key = a.areas[0].lower() if a.areas else a.identifier
        prev = by_area.get(key)
        if prev is None or a.level > prev.level:
            by_area[key] = a

    result = list(by_area.values())
    log.info("HTML fallback: %d okresných výstrah", len(result))
    return result
