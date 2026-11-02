"""Parser HTML tabuľky výstrah SHMÚ podľa okresov (page=987).

Pre každý okres zistí maximálny stupeň a skutočný časový rozsah
platnosti (prvá–posledná hodina so stupňom ≥ 1, aj cez viac dní).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from lxml import html

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Bratislava")

DEFAULT_DETAIL_URL = (
    "https://www.shmu.sk/sk/?page=987&id=&d=0&jav=&roll=KSK%7CPSK"
)

_KRAJ_RE = re.compile(
    r"(kraj|bratislavský|banskobystrický|trenčiansky|košický|"
    r"nitriansky|trnavský|prešovský|žilinský)",
    re.I,
)


def _is_kraj_row(name: str) -> bool:
    n = name.strip()
    if not n:
        return True
    if n.startswith("**") and n.endswith("**"):
        return True
    return bool(_KRAJ_RE.search(n)) and "mesto" not in n.lower() and "okolie" not in n.lower()


def _normalize_district(name: str) -> str:
    return " ".join(name.replace("**", "").split())


def _hour_levels_from_row(cells: list) -> List[int]:
    name_idx = None
    for i, c in enumerate(cells):
        t = (c or "").strip()
        if t and not t.isdigit() and t not in ("Región", "Jav"):
            name_idx = i
            break
    if name_idx is None:
        return []
    rest = cells[name_idx + 1 :]
    levels: List[int] = []
    for c in rest:
        t = (c or "").strip()
        if t.isdigit() and 0 <= int(t) <= 3:
            levels.append(int(t))
        elif t == "":
            levels.append(0)
    if len(levels) > 24:
        levels = levels[-24:]
    return levels


def _range_from_levels(
    levels: List[int],
    day_base: datetime,
) -> Tuple[Optional[datetime], Optional[datetime], int]:
    max_lvl = max(levels) if levels else 0
    if max_lvl < 1:
        return None, None, 0
    first = next(i for i, v in enumerate(levels) if v >= 1)
    last = max(i for i, v in enumerate(levels) if v >= 1)
    offset = 24 - len(levels) if 0 < len(levels) < 24 else 0
    first_h = first + offset
    last_h = last + offset
    base = day_base.replace(hour=0, minute=0, second=0, microsecond=0)
    eff = base + timedelta(hours=first_h)
    exp = base + timedelta(hours=last_h + 1)
    return eff, exp, max_lvl


def _day_base_from_page(tree, day_offset: int, now_local: datetime) -> datetime:
    text = tree.text_content()
    m = re.search(r"Aktualizované:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        base = datetime(y, mo, d, tzinfo=TZ)
    else:
        base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=day_offset)


def _build_day_url(base_url: str, day: int, regions: Optional[List[str]]) -> str:
    if "page=987" not in (base_url or ""):
        base_url = "https://www.shmu.sk/sk/?page=987"
    if re.search(r"[?&]d=\d+", base_url):
        url = re.sub(r"([?&]d=)\d+", rf"\g<1>{day}", base_url)
    else:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}d={day}"
    if regions and "roll=" not in url:
        roll = quote("|".join(r.upper() for r in regions), safe="|")
        url = f"{url}&roll={roll}"
    return url


def _parse_day_table(tree, day_base: datetime) -> Dict[str, Tuple[int, datetime, datetime]]:
    out: Dict[str, Tuple[int, datetime, datetime]] = {}
    for table in tree.xpath("//table"):
        for tr in table.xpath(".//tr"):
            cells = ["".join(td.itertext()).strip() for td in tr.xpath("./td|./th")]
            if len(cells) < 3:
                continue
            name = ""
            for c in cells[:4]:
                if c and not c.isdigit() and c not in ("Región", "Jav", "0"):
                    name = c
                    break
            if not name or _is_kraj_row(name):
                continue
            district = _normalize_district(name)
            levels = _hour_levels_from_row(cells)
            eff, exp, max_lvl = _range_from_levels(levels, day_base)
            if max_lvl < 1 or eff is None or exp is None:
                continue
            out[district] = (max_lvl, eff, exp)
    return out


def fetch_html_alerts(
    url: str,
    session: Optional[requests.Session] = None,
    regions: Optional[List[str]] = None,
    days_ahead: int = 3,
) -> List[Alert]:
    """Tabuľky dnes + ďalšie dni → celý rozsah platnosti pre každý okres."""
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "SHMU-APRS-Alerts/1.2 (Amateur Radio)",
        "Accept-Language": "sk,en;q=0.8",
    })

    now_local = datetime.now(TZ)
    agg: Dict[str, Tuple[int, datetime, datetime]] = {}

    for day in range(max(1, days_ahead)):
        day_url = _build_day_url(url or DEFAULT_DETAIL_URL, day, regions)
        try:
            r = session.get(day_url, timeout=45)
            r.raise_for_status()
        except requests.RequestException as e:
            log.error("HTML deň %s zlyhal: %s", day, e)
            continue

        tree = html.fromstring(r.content)
        day_base = _day_base_from_page(tree, day, now_local)
        day_data = _parse_day_table(tree, day_base)

        for district, (lvl, eff, exp) in day_data.items():
            if district not in agg:
                agg[district] = (lvl, eff, exp)
            else:
                prev_lvl, prev_eff, prev_exp = agg[district]
                agg[district] = (
                    max(prev_lvl, lvl),
                    min(prev_eff, eff),
                    max(prev_exp, exp),
                )
            log.info(
                "HTML: %s deň+%s → %s.st. %s–%s",
                district, day, lvl,
                eff.strftime("%d.%m %H:%M"),
                exp.strftime("%d.%m %H:%M"),
            )

    alerts: List[Alert] = []
    for district, (lvl, eff, exp) in agg.items():
        level = AlertLevel(lvl)
        safe = re.sub(r"[^A-Za-z0-9]", "", district)[:12] or "OKR"
        identifier = f"HTML-{eff.strftime('%Y%m%d')}-{safe}"
        desc = (
            f"Výstraha {level.degree_sk} – {district}: "
            f"{eff.strftime('%d.%m.%Y %H:%M')} – {exp.strftime('%d.%m.%Y %H:%M')}"
        )
        alerts.append(Alert(
            identifier=identifier,
            event="Výstraha",
            level=level,
            headline=f"SHMÚ výstraha {level.degree_sk} – {district}",
            description=desc,
            areas=[district],
            regions=[],
            effective=eff.astimezone(timezone.utc),
            expires=exp.astimezone(timezone.utc),
            sent=datetime.now(timezone.utc),
            source="HTML",
        ))

    log.info("HTML fallback: %d okresných výstrah (celý rozsah)", len(alerts))
    return alerts
