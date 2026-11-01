"""Dátové modely výstrah."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Optional, Tuple


class AlertLevel(IntEnum):
    NONE = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3

    @property
    def color_sk(self) -> str:
        return {0: "žiadna", 1: "žltá", 2: "oranžová", 3: "červená"}.get(self.value, "?")

    @property
    def color_en(self) -> str:
        return {0: "none", 1: "yellow", 2: "orange", 3: "red"}.get(self.value, "?")


_EVENT_SYMBOLS: dict[str, Tuple[str, str]] = {
    "búrka": ("\\", "T"), "búrk": ("\\", "T"), "thunderstorm": ("\\", "T"),
    "vietor": ("\\", "<"), "wind": ("\\", "<"), "víchr": ("\\", "<"),
    "dážď": ("\\", "`"), "rain": ("\\", "`"), "lejak": ("\\", "`"),
    "hmla": ("\\", "H"), "fog": ("\\", "H"),
    "sneženie": ("\\", "*"), "sneh": ("\\", "*"), "snow": ("\\", "*"), "záveje": ("\\", "*"),
    "poľadovica": ("\\", "F"), "mráz": ("\\", "F"), "ľad": ("\\", "F"),
    "horúčava": ("\\", "U"), "vysoké teploty": ("\\", "U"), "nízke teploty": ("\\", "F"),
}


def _symbol_for_event(event: str) -> Optional[Tuple[str, str]]:
    low = (event or "").lower()
    for key, sym in _EVENT_SYMBOLS.items():
        if key in low:
            return sym
    return None


@dataclass
class Alert:
    identifier: str
    event: str
    level: AlertLevel
    headline: str
    description: str
    instruction: str = ""
    areas: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    effective: Optional[datetime] = None
    expires: Optional[datetime] = None
    sent: Optional[datetime] = None
    urgency: str = ""
    severity: str = ""
    certainty: str = ""
    source: str = "SHMU"

    def is_active(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.expires and now > self.expires:
            return False
        if self.effective and now < self.effective:
            return False
        return True

    def aprs_symbol(self) -> Tuple[str, str]:
        by_event = _symbol_for_event(self.event)
        if by_event:
            table, code = by_event
            if self.level == AlertLevel.RED and code not in ("T", "!"):
                return "\\", "!"
            return table, code
        if self.level == AlertLevel.RED:
            return "\\", "!"
        if self.level == AlertLevel.ORANGE:
            return "\\", "W"
        return "\\", "<"

    def short_comment(self, max_len: int = 43) -> str:
        color = self.level.color_sk.upper()
        areas = ",".join(self.areas[:2]) if self.areas else "SK"
        base = f"{color} {self.event} {areas}"
        if len(base) > max_len:
            base = base[: max_len - 1] + "…"
        return base

    def full_text(self) -> str:
        parts = [f"SHMU {self.level.color_sk.upper()} {self.level.value}.st.", self.event]
        if self.areas:
            parts.append(" / ".join(self.areas[:4]))
        if self.expires:
            parts.append(f"do {self.expires.astimezone().strftime('%d.%m %H:%M')}")
        return " | ".join(parts)

    def object_name(self, district_code: str = "") -> str:
        """Meno APRS objektu (max 9 znakov). district_code = skratka okresu (KE, PO…)."""
        code = (district_code or "SK")[:4].upper()
        rest = 9 - 2 - len(code)
        if rest < 1:
            code = code[:3]
            rest = 4
        short_id = self.identifier[-rest:] if len(self.identifier) >= rest else self.identifier
        name = f"SH{code}{short_id}"
        return name[:9].ljust(9)


@dataclass
class ActiveObject:
    alert: Alert
    object_name: str
    last_sent: datetime
    kill_sent: bool = False
