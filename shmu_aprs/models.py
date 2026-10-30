"""Dátové modely výstrah."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Optional


class AlertLevel(IntEnum):
    """Stupeň výstrahy podľa SHMÚ / Meteoalarm farieb."""
    NONE = 0
    YELLOW = 1   # 1. stupeň – žltá
    ORANGE = 2   # 2. stupeň – oranžová
    RED = 3      # 3. stupeň – červená

    @property
    def color_sk(self) -> str:
        return {
            0: "žiadna",
            1: "žltá",
            2: "oranžová",
            3: "červená",
        }.get(self.value, "?")

    @property
    def color_en(self) -> str:
        return {
            0: "none",
            1: "yellow",
            2: "orange",
            3: "red",
        }.get(self.value, "?")

    @property
    def symbol(self) -> str:
        """APRS symbol (primary table) pre úroveň."""
        # W = WX station,  / = primary,  \ = alternate
        # Pre výstrahy použijeme 'W' + farba v komentári
        return "W"


@dataclass
class Alert:
    """Jedna meteorologická výstraha."""
    identifier: str                     # unikátne ID (CAP identifier)
    event: str                          # názov javu (Búrka, Vietor, Hmla…)
    level: AlertLevel
    headline: str
    description: str
    instruction: str = ""
    areas: List[str] = field(default_factory=list)   # okresy / kraje
    regions: List[str] = field(default_factory=list) # kódy krajov (KSK, PSK…)
    effective: Optional[datetime] = None
    expires: Optional[datetime] = None
    sent: Optional[datetime] = None
    urgency: str = ""
    severity: str = ""
    certainty: str = ""
    source: str = "SHMU"                # CAP / HTML

    def is_active(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.expires and now > self.expires:
            return False
        if self.effective and now < self.effective:
            return False
        return True

    def short_comment(self, max_len: int = 43) -> str:
        """Komentár vhodný do APRS objektu (max ~43 znakov)."""
        color = self.level.color_sk.upper()
        areas = ",".join(self.areas[:2]) if self.areas else "SK"
        base = f"{color} {self.event} {areas}"
        if len(base) > max_len:
            base = base[: max_len - 1] + "…"
        return base

    def full_text(self) -> str:
        """Dlhší text pre bulletin / status."""
        parts = [
            f"SHMU {self.level.color_sk.upper()} {self.level.value}.st.",
            self.event,
        ]
        if self.areas:
            parts.append(" / ".join(self.areas[:4]))
        if self.expires:
            exp = self.expires.astimezone().strftime("%d.%m %H:%M")
            parts.append(f"do {exp}")
        return " | ".join(parts)

    def object_name(self) -> str:
        """Meno APRS objektu (max 9 znakov)."""
        # SHMU + skrátené ID
        short_id = self.identifier[-5:] if len(self.identifier) > 5 else self.identifier
        name = f"SH{short_id}"
        return name[:9].ljust(9)


@dataclass
class ActiveObject:
    """Sledovaný APRS objekt, ktorý sme vyslali."""
    alert: Alert
    object_name: str
    last_sent: datetime
    kill_sent: bool = False
