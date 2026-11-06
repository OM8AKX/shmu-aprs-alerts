"""Parser HTML tabuľky výstrah SHMÚ podľa okresov (page=987).

Pre každý okres zistí maximálny stupeň, druh javu (Hmla, Vietor, …)
a skutočný časový rozsah platnosti (aj cez viac dní).
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

# mapovanie alt/title ikon → krátky názov javu
_EVENT_FROM_ICON = re.compile(
    r"(hmla|vietor|víchr|búrka|búrk|dážď|lejak|sneh|sneženie|záveje|"
    r"poľadovica|mráz|ľad|horúčava|povodeň|teplot)",
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


def _normalize_event(raw: str) -> str:
    """Z alt/title ikony urobí krátky názov javu (Hmla, Vietor, …)."""
    t = " ".join((raw or "").split()).strip()
    if not t:
        return ""
    # "1. stupeň - Hmla" → Hmla
    if " - " in t:
        t = t.split(" - ")[-1].strip()
    m = _EVENT_FROM_ICON.search(t)
    if m:
        word = m.group(1)
        low = word.lower()
        mapping = {
            "hmla": "Hmla",
            "vietor": "Vietor",
            "víchr": "Víchrica",
            "búrka": "Búrka",
            "búrk": "Búrka",
            "dážď": "Dážď",
            "lejak": "Lejak",
            "sneh": "Sneh",
            "sneženie": "Sneženie",
            "záveje": "Záveje",
            "poľadovica": "Poľadovica",
            "mráz": "Mráz",
            "ľad": "Ľad",
            "horúčava": "Horúčava",
            "povodeň": "Povodeň",
            "teplot": "Teplota",
        }
        return mapping.get(low, word.capitalize())
    parts = [p for p in re.split(r"[\s,;/]+", t) if p and not p[0].isdigit()]
    return parts[0][:20] if parts else t[:20]


def _event_from_row(tr) -> str:
    """Druh javu z <img alt/title> v riadku, inak prázdny reťazec."""
    for img in tr.xpath(".//img"):
        for attr in ("alt", "title"):
            val = (img.get(attr) or "").strip()
            if val and "načítav" not in val.lower():
                ev = _normalize_event(val)
                if ev:
                    return ev
    return ""


def _event_from_page(tree) -> str:
    """Aktívny jav z kariet (napr. odkaz Hmla s jav=…)."""
    for a in tree.xpath("//a[contains(@href,'jav=')]"):
        href = a.get("href") or ""
        if re.search(r"jav=\d+", href):
            text = " ".join(a.text_content().split()).strip()
            if text and text.lower() not in ("legenda", "návrat späť"):
                return _normalize_event(text) or text[:20]
    for img in tree.xpath("//table//img")[:5]:
        for attr in ("alt", "title"):
            val = (img.get(attr) or "").strip()
            if val:
                ev = _normalize_event(val)
                if ev:
                    return ev
    return "Výstraha"


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
    for a in tree.xpath("//a[contains(@href,'d=')]"):
        title = (a.get("title") or "") + " " + " ".join(a.text_content().split())
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", title)
        href = a.get("href") or ""
        dm = re.search(r"[?&]d=(\d+)", href)
        if m and dm and int(dm.group(1)) == day_offset:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=TZ)
            except ValueError:
                pass
    return (now_local + timedelta(days=day_offset)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


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


def _parse_day_table(
    tree, day_base: datetime, page_event: str
) -> Dict[Tuple[str, str], Tuple[int, datetime, datetime]]:
    """Kľúč = (okres, jav) → (stupeň, effective, expires)."""
    out: Dict[Tuple[str, str], Tuple[int, datetime, datetime]] = {}
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
            event = _event_from_row(tr) or page_event or "Výstraha"
            levels = _hour_levels_from_row(cells)
            eff, exp, max_lvl = _range_from_levels(levels, day_base)
            if max_lvl < 1 or eff is None or exp is None:
                continue
            key = (district, event)
            if key not in out:
                out[key] = (max_lvl, eff, exp)
            else:
                prev_lvl, prev_eff, prev_exp = out[key]
                out[key] = (
                    max(prev_lvl, max_lvl),
                    min(prev_eff, eff),
                    max(prev_exp, exp),
                )
    return out


def fetch_html_alerts(
    url: str,
    session: Optional[requests.Session] = None,
    regions: Optional[List[str]] = None,
    days_ahead: int = 3,
) -> List[Alert]:
    """Tabuľky dnes + ďalšie dni → celý rozsah platnosti pre každý okres a jav."""
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "SHMU-APRS-Alerts/1.3 (Amateur Radio)",
        "Accept-Language": "sk,en;q=0.8",
    })

    now_local = datetime.now(TZ)
    # (okres, jav) → (lvl, eff, exp)
    agg: Dict[Tuple[str, str], Tuple[int, datetime, datetime]] = {}

    for day in range(max(1, days_ahead)):
        day_url = _build_day_url(url or DEFAULT_DETAIL_URL, day, regions)
        try:
            r = session.get(day_url, timeout=45)
            r.raise_for_status()
        except requests.RequestException as e:
            log.error("HTML deň %s zlyhal: %s", day, e)
            continue

        tree = html.fromstring(r.content)
        page_event = _event_from_page(tree)
        day_base = _day_base_from_page(tree, day, now_local)
        day_data = _parse_day_table(tree, day_base, page_event)

        for (district, event), (lvl, eff, exp) in day_data.items():
            key = (district, event)
            if key not in agg:
                agg[key] = (lvl, eff, exp)
            else:
                prev_lvl, prev_eff, prev_exp = agg[key]
                agg[key] = (
                    max(prev_lvl, lvl),
                    min(prev_eff, eff),
                    max(prev_exp, exp),
                )
            log.info(
                "HTML: %s / %s deň+%s → %s.st. %s–%s",
                district, event, day, lvl,
                eff.strftime("%d.%m %H:%M"),
                exp.strftime("%d.%m %H:%M"),
            )

    alerts: List[Alert] = []
    for (district, event), (lvl, eff, exp) in agg.items():
        level = AlertLevel(lvl)
        safe_d = re.sub(r"[^A-Za-z0-9]", "", district)[:8] or "OKR"
        safe_e = re.sub(r"[^A-Za-z0-9]", "", event)[:4] or "X"
        identifier = f"HTML-{eff.strftime('%Y%m%d')}-{safe_d}-{safe_e}"
        desc = (
            f"Výstraha {level.degree_sk} – {event} – {district}: "
            f"{eff.strftime('%d.%m.%Y %H:%M')} – {exp.strftime('%d.%m.%Y %H:%M')}"
        )
        alerts.append(Alert(
            identifier=identifier,
            event=event,
            level=level,
            headline=f"SHMÚ {event} {level.degree_sk} – {district}",
            description=desc,
            areas=[district],
            regions=[],
            effective=eff.astimezone(timezone.utc),
            expires=exp.astimezone(timezone.utc),
            sent=datetime.now(timezone.utc),
            source="HTML",
        ))

    log.info("HTML fallback: %d okresných výstrah (s druhom javu)", len(alerts))
    return alerts
