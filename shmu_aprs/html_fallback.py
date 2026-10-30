"""Jednoduchý fallback parser HTML stránky SHMÚ (keď CAP nie je dostupný)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import requests
from lxml import html

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

# Mapovanie názvov javov
EVENT_MAP = {
    "búrka": "Búrka",
    "dážď": "Dážď",
    "hmla": "Hmla",
    "poľadovica": "Poľadovica",
    "mráz": "Mráz",
    "sneženie": "Sneženie",
    "snehové jazyky": "Záveje",
    "záveje": "Záveje",
    "vietor": "Vietor",
    "vietor na horách": "Vietor na horách",
    "teploty nízke": "Nízke teploty",
    "teploty vysoké": "Vysoké teploty",
    "horúčava": "Vysoké teploty",
}


def _guess_level(text: str) -> AlertLevel:
    text = text.lower()
    if "3. stup" in text or "3.st" in text or "červen" in text:
        return AlertLevel.RED
    if "2. stup" in text or "2.st" in text or "oranž" in text:
        return AlertLevel.ORANGE
    if "1. stup" in text or "1.st" in text or "žlt" in text:
        return AlertLevel.YELLOW
    return AlertLevel.YELLOW


def fetch_html_alerts(url: str, session: Optional[requests.Session] = None) -> List[Alert]:
    """
    Velmi jednoduchý parser – extrahuje aktuálne výstrahy z hlavnej stránky.
    Nie je 100 % spoľahlivý (závisí od HTML), preto je to len fallback.
    """
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "SHMU-APRS-Alerts/1.0 (Amateur Radio)",
        "Accept-Language": "sk,en;q=0.8",
    })

    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("HTML fallback zlyhal: %s", e)
        return []

    tree = html.fromstring(r.content)
    alerts: List[Alert] = []
    now = datetime.now(timezone.utc)

    # Hľadáme texty typu „SHMÚ vydal meteorologické výstrahy – 1. stupeň“
    page_text = tree.text_content()

    # Nájdeme aktuálny maximálny stupeň
    level = AlertLevel.NONE
    m = re.search(r"vydal.*?výstrahy.*?(\d)\.\s*stup", page_text, re.I)
    if m:
        level = AlertLevel(int(m.group(1)))

    if level == AlertLevel.NONE:
        log.debug("HTML: žiadna aktívna výstraha detekovaná")
        return []

    # Skúsime nájsť konkrétne javy z tabuliek / legendy
    events_found = set()
    for key, nice in EVENT_MAP.items():
        if key in page_text.lower():
            events_found.add(nice)

    if not events_found:
        events_found.add("Výstraha")

    # Pre jednoduchosť vytvoríme jednu súhrnnú výstrahu
    # (CAP poskytuje oveľa lepšie detaily)
    identifier = f"HTML-{now.strftime('%Y%m%d%H')}"
    headline = f"SHMÚ výstraha {level.value}. stupňa"
    description = f"Aktívne javy: {', '.join(sorted(events_found))}"

    alerts.append(Alert(
        identifier=identifier,
        event="/".join(sorted(events_found)[:3]),
        level=level,
        headline=headline,
        description=description,
        areas=["Slovensko"],
        regions=[],
        effective=now - timedelta(hours=1),
        expires=now + timedelta(hours=12),
        sent=now,
        source="HTML",
    ))

    log.info("HTML fallback: nájdená výstraha úrovne %s", level.color_sk)
    return alerts
