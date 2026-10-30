"""Parser CAP 1.2 XML zo SHMÚ opendata."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

import requests
from dateutil import parser as date_parser
from lxml import etree

from .models import Alert, AlertLevel

log = logging.getLogger(__name__)

NS = {
    "cap": "urn:oasis:names:tc:emergency:cap:1.2",
}

SEVERITY_MAP = {
    "Minor": AlertLevel.YELLOW,
    "Moderate": AlertLevel.ORANGE,
    "Severe": AlertLevel.RED,
    "Extreme": AlertLevel.RED,
}

REGION_CODES = {
    "košický": "KSK",
    "košice": "KSK",
    "prešovský": "PSK",
    "prešov": "PSK",
    "banskobystrický": "BBSK",
    "banská bystrica": "BBSK",
    "žilinský": "ZSK",
    "žilina": "ZSK",
    "trenčiansky": "TSK",
    "trenčín": "TSK",
    "trnavský": "TTSK",
    "trnava": "TTSK",
    "nitriansky": "NSK",
    "nitra": "NSK",
    "bratislavský": "BSK",
    "bratislava": "BSK",
}


def _parse_dt(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        dt = date_parser.isoparse(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _level_from_info(info: etree._Element) -> AlertLevel:
    severity = (info.findtext("cap:severity", namespaces=NS) or "").strip()
    if severity in SEVERITY_MAP:
        return SEVERITY_MAP[severity]

    for param in info.findall("cap:parameter", namespaces=NS):
        name = (param.findtext("cap:valueName", namespaces=NS) or "").lower()
        value = (param.findtext("cap:value", namespaces=NS) or "").strip()
        if "stup" in name or "level" in name or "severity" in name:
            try:
                n = int(re.search(r"\d+", value).group())
                if 1 <= n <= 3:
                    return AlertLevel(n)
            except (AttributeError, ValueError):
                pass

    urgency = (info.findtext("cap:urgency", namespaces=NS) or "").lower()
    if urgency in ("immediate", "expected"):
        return AlertLevel.ORANGE
    return AlertLevel.YELLOW


def _extract_areas(info: etree._Element) -> tuple[List[str], List[str]]:
    areas: List[str] = []
    regions: List[str] = []

    for area in info.findall("cap:area", namespaces=NS):
        desc = (area.findtext("cap:areaDesc", namespaces=NS) or "").strip()
        if desc:
            for part in re.split(r"[,;]", desc):
                part = part.strip()
                if not part:
                    continue
                areas.append(part)
                low = part.lower()
                for key, code in REGION_CODES.items():
                    if key in low and code not in regions:
                        regions.append(code)

        for geo in area.findall("cap:geocode", namespaces=NS):
            name = (geo.findtext("cap:valueName", namespaces=NS) or "").lower()
            val = (geo.findtext("cap:value", namespaces=NS) or "").strip()
            if val and ("region" in name or "kraj" in name or "NUTS" in name.upper()):
                if val not in regions:
                    regions.append(val)

    return areas, regions


def parse_cap_xml(content: bytes | str) -> List[Alert]:
    if isinstance(content, str):
        content = content.encode("utf-8")

    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError as e:
        log.warning("Neplatný CAP XML: %s", e)
        return []

    alerts: List[Alert] = []

    alert_elems = []
    if root.tag.endswith("alert"):
        alert_elems = [root]
    else:
        alert_elems = root.findall(".//{urn:oasis:names:tc:emergency:cap:1.2}alert")
        if not alert_elems:
            alert_elems = root.findall(".//alert")

    for alert_el in alert_elems:
        identifier = (alert_el.findtext("cap:identifier", namespaces=NS)
                      or alert_el.findtext("identifier") or "").strip()
        if not identifier:
            continue

        sent = _parse_dt(alert_el.findtext("cap:sent", namespaces=NS)
                         or alert_el.findtext("sent"))
        status = (alert_el.findtext("cap:status", namespaces=NS)
                  or alert_el.findtext("status") or "").strip()
        msg_type = (alert_el.findtext("cap:msgType", namespaces=NS)
                    or alert_el.findtext("msgType") or "").strip()

        if status and status.lower() not in ("actual", "exercise"):
            continue

        for info in alert_el.findall("cap:info", namespaces=NS):
            lang = (info.findtext("cap:language", namespaces=NS) or "sk").lower()
            if lang.startswith("en") and any(
                (i.findtext("cap:language", namespaces=NS) or "").lower().startswith("sk")
                for i in alert_el.findall("cap:info", namespaces=NS)
            ):
                continue

            event = (info.findtext("cap:event", namespaces=NS) or "Výstraha").strip()
            headline = (info.findtext("cap:headline", namespaces=NS) or event).strip()
            description = (info.findtext("cap:description", namespaces=NS) or "").strip()
            instruction = (info.findtext("cap:instruction", namespaces=NS) or "").strip()
            effective = _parse_dt(info.findtext("cap:effective", namespaces=NS))
            expires = _parse_dt(info.findtext("cap:expires", namespaces=NS))
            urgency = (info.findtext("cap:urgency", namespaces=NS) or "").strip()
            severity = (info.findtext("cap:severity", namespaces=NS) or "").strip()
            certainty = (info.findtext("cap:certainty", namespaces=NS) or "").strip()

            level = _level_from_info(info)
            areas, regions = _extract_areas(info)

            alerts.append(Alert(
                identifier=identifier,
                event=event,
                level=level,
                headline=headline,
                description=description,
                instruction=instruction,
                areas=areas,
                regions=regions,
                effective=effective or sent,
                expires=expires,
                sent=sent,
                urgency=urgency,
                severity=severity,
                certainty=certainty,
                source="CAP",
            ))

    return alerts


def fetch_cap_alerts(base_url: str, session: Optional[requests.Session] = None) -> List[Alert]:
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "SHMU-APRS-Alerts/1.0 (Amateur Radio; Raspberry Pi)",
        "Accept": "application/xml, text/xml, */*",
    })

    alerts: List[Alert] = []

    try:
        r = session.get(base_url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Nepodarilo sa stiahnuť CAP index %s: %s", base_url, e)
        return []

    hrefs = re.findall(r'href="([^"]+\.xml)"', r.text, re.I)
    if not hrefs:
        if "xml" in r.headers.get("Content-Type", "").lower() or r.text.strip().startswith("<?xml"):
            return parse_cap_xml(r.content)
        log.info("CAP adresár je prázdny alebo bez .xml súborov")
        return []

    for href in hrefs:
        url = urljoin(base_url, href)
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            alerts.extend(parse_cap_xml(resp.content))
            log.debug("Načítaný CAP: %s (%d výstrah)", href, len(alerts))
        except requests.RequestException as e:
            log.warning("Chyba pri sťahovaní %s: %s", url, e)

    return alerts
