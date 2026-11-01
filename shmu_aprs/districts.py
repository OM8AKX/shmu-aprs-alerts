"""Stredy okresov SR – približné súradnice pre APRS objekty."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

DISTRICT_CENTERS: Dict[str, Tuple[float, float]] = {
    "bratislava": (48.1486, 17.1077),
    "bratislava i": (48.1486, 17.1077),
    "bratislava ii": (48.1486, 17.1077),
    "bratislava iii": (48.1486, 17.1077),
    "bratislava iv": (48.1486, 17.1077),
    "bratislava v": (48.1486, 17.1077),
    "malacky": (48.4360, 17.0217),
    "pezinok": (48.2878, 17.2667),
    "senec": (48.2200, 17.4000),
    "trnava": (48.3774, 17.5883),
    "dunajská streda": (47.9927, 17.6122),
    "galanta": (48.1900, 17.7280),
    "hlohovec": (48.4310, 17.8030),
    "piešťany": (48.5910, 17.8270),
    "senica": (48.6790, 17.3620),
    "skalica": (48.8450, 17.2260),
    "trenčín": (48.8945, 18.0444),
    "banovce nad bebravou": (48.7190, 18.2580),
    "bánovce nad bebravou": (48.7190, 18.2580),
    "ilava": (48.9960, 18.2350),
    "myjava": (48.7590, 17.5650),
    "nové mesto nad váhom": (48.7550, 17.8300),
    "partizánske": (48.6280, 18.3770),
    "póvazská bystrica": (49.1160, 18.4320),
    "považská bystrica": (49.1160, 18.4320),
    "prievidza": (48.7740, 18.6270),
    "púchov": (49.1250, 18.3260),
    "nitra": (48.3060, 18.0760),
    "komárno": (47.7630, 18.1230),
    "levice": (48.2150, 18.6070),
    "nové zámky": (47.9850, 18.1610),
    "šala": (48.1510, 17.8750),
    "sala": (48.1510, 17.8750),
    "topoľčany": (48.5610, 18.1770),
    "topolcany": (48.5610, 18.1770),
    "zlaté moravce": (48.3830, 18.4000),
    "žilina": (49.2230, 18.7390),
    "bytča": (49.2240, 18.5590),
    "čadca": (49.4390, 18.7870),
    "cadca": (49.4390, 18.7870),
    "dolný kubín": (49.2100, 19.2970),
    "kysucké nové mesto": (49.3020, 18.7870),
    "liptovský mikuláš": (49.0840, 19.6120),
    "martin": (49.0660, 18.9220),
    "námestovo": (49.4070, 19.4790),
    "rúžomberok": (49.0810, 19.3040),
    "ruzomberok": (49.0810, 19.3040),
    "turčianske teplice": (48.9090, 18.8630),
    "tvrdošín": (49.3340, 19.5560),
    "banská bystrica": (48.7360, 19.1460),
    "banska bystrica": (48.7360, 19.1460),
    "banská štiavnica": (48.4590, 18.8930),
    "brezno": (48.8040, 19.6440),
    "detva": (48.5610, 19.4190),
    "krupina": (48.3550, 19.0670),
    "lucenec": (48.3320, 19.6670),
    "lučenec": (48.3320, 19.6670),
    "poltár": (48.4310, 19.7940),
    "revúca": (48.6840, 20.1140),
    "rimavská sobota": (48.3830, 20.0180),
    "veľký krtíš": (48.2100, 19.3520),
    "velky krtis": (48.2100, 19.3520),
    "zvolen": (48.5740, 19.1530),
    "žiar nad hronom": (48.5880, 18.8500),
    "ziar nad hronom": (48.5880, 18.8500),
    "žarnovica": (48.4830, 18.7220),
    "prešov": (48.9980, 21.2400),
    "presov": (48.9980, 21.2400),
    "bardejov": (49.2910, 21.2730),
    "humenné": (48.9370, 21.9160),
    "humenne": (48.9370, 21.9160),
    "kežmarok": (49.1360, 20.4290),
    "kezmarok": (49.1360, 20.4290),
    "levoča": (49.0220, 20.5920),
    "levoca": (49.0220, 20.5920),
    "medzilaborce": (49.2710, 21.9040),
    "poprad": (49.0610, 20.2980),
    "sabinov": (49.1030, 21.0980),
    "snina": (48.9880, 22.1520),
    "stará ľubovňa": (49.3020, 20.6910),
    "stara lubovna": (49.3020, 20.6910),
    "stroplkov": (49.2030, 21.6520),
    "stropkov": (49.2030, 21.6520),
    "svidník": (49.3080, 21.5700),
    "svidnik": (49.3080, 21.5700),
    "vranov nad topľou": (48.8880, 21.6850),
    "vranov nad toplou": (48.8880, 21.6850),
    "košice": (48.7164, 21.2611),
    "kosice": (48.7164, 21.2611),
    "košice-okolie": (48.7164, 21.2611),
    "košice okolie": (48.7164, 21.2611),
    "gelnica": (48.8520, 20.9340),
    "michalovce": (48.7540, 21.9190),
    "rožňava": (48.6600, 20.5330),
    "roznava": (48.6600, 20.5330),
    "sobrance": (48.7460, 22.1810),
    "spišská nová ves": (48.9450, 20.5680),
    "spisska nova ves": (48.9450, 20.5680),
    "trebišov": (48.6290, 21.7190),
    "trebisov": (48.6290, 21.7190),
}

DISTRICT_SHORT: Dict[str, str] = {
    "bratislava": "BA", "malacky": "MA", "pezinok": "PK", "senec": "SC",
    "trnava": "TT", "dunajská streda": "DS", "galanta": "GA", "hlohovec": "HC",
    "piešťany": "PN", "senica": "SE", "skalica": "SI",
    "trenčín": "TN", "bánovce nad bebravou": "BN", "banovce nad bebravou": "BN",
    "ilava": "IL", "myjava": "MY", "nové mesto nad váhom": "NM",
    "partizánske": "PE", "považská bystrica": "PB", "póvazská bystrica": "PB",
    "prievidza": "PD", "púchov": "PU",
    "nitra": "NR", "komárno": "KN", "levice": "LV", "nové zámky": "NZ",
    "šala": "SA", "sala": "SA", "topoľčany": "TO", "topolcany": "TO", "zlaté moravce": "ZM",
    "žilina": "ZA", "bytča": "BY", "čadca": "CA", "cadca": "CA",
    "dolný kubín": "DK", "kysucké nové mesto": "KM", "liptovský mikuláš": "LM",
    "martin": "MT", "námestovo": "NO", "rúžomberok": "RK", "ruzomberok": "RK",
    "turčianske teplice": "TR", "tvrdošín": "TS",
    "banská bystrica": "BB", "banska bystrica": "BB", "banská štiavnica": "BS",
    "brezno": "BR", "detva": "DT", "krupina": "KA", "lučenec": "LC", "lucenec": "LC",
    "poltár": "PT", "revúca": "RA", "rimavská sobota": "RS",
    "veľký krtíš": "VK", "velky krtis": "VK", "zvolen": "ZV",
    "žiar nad hronom": "ZH", "ziar nad hronom": "ZH", "žarnovica": "ZC",
    "prešov": "PO", "presov": "PO", "bardejov": "BJ", "humenné": "HE", "humenne": "HE",
    "kežmarok": "KK", "kezmarok": "KK", "levoča": "LE", "levoca": "LE",
    "medzilaborce": "ML", "poprad": "PP", "sabinov": "SB", "snina": "SV",
    "stará ľubovňa": "SL", "stara lubovna": "SL", "stropkov": "SP", "stroplkov": "SP",
    "svidník": "SK", "svidnik": "SK", "vranov nad topľou": "VT", "vranov nad toplou": "VT",
    "košice": "KE", "kosice": "KE", "košice-okolie": "KO", "košice okolie": "KO",
    "gelnica": "GL", "michalovce": "MI", "rožňava": "RV", "roznava": "RV",
    "sobrance": "SO", "spišská nová ves": "SN", "spisska nova ves": "SN",
    "trebišov": "TV", "trebisov": "TV",
}

REGION_CENTERS: Dict[str, Tuple[float, float]] = {
    "BSK": (48.15, 17.11),
    "TTSK": (48.38, 17.59),
    "TSK": (48.89, 18.04),
    "NSK": (48.31, 18.08),
    "ZSK": (49.22, 18.74),
    "BBSK": (48.74, 19.15),
    "PSK": (49.00, 21.24),
    "KSK": (48.72, 21.26),
}

DEFAULT_CENTER = (48.67, 19.70)


def _norm(name: str) -> str:
    return " ".join(name.lower().replace("–", "-").replace("—", "-").split())


def lookup_district(name: str) -> Optional[Tuple[str, float, float]]:
    n = _norm(name)
    if n in DISTRICT_CENTERS:
        lat, lon = DISTRICT_CENTERS[n]
        return n, lat, lon
    for key, (lat, lon) in DISTRICT_CENTERS.items():
        if key in n or n in key:
            return key, lat, lon
    return None


def short_code(district_key: str) -> str:
    return DISTRICT_SHORT.get(district_key, district_key[:4].upper())


def resolve_alert_positions(
    areas: List[str],
    regions: List[str],
) -> List[Tuple[str, float, float]]:
    found: Dict[str, Tuple[str, float, float]] = {}
    for area in areas or []:
        hit = lookup_district(area)
        if hit:
            key, lat, lon = hit
            found[key] = (short_code(key), lat, lon)
    if not found:
        for reg in regions or []:
            code = reg.upper().strip()
            if code in REGION_CENTERS:
                lat, lon = REGION_CENTERS[code]
                found[code] = (code[:4], lat, lon)
    if not found:
        lat, lon = DEFAULT_CENTER
        return [("SK", lat, lon)]
    return list(found.values())
