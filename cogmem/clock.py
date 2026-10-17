"""Часы памяти.

Вся память работает только через эти часы, а не через datetime.now().
Это позволяет в тестах «прожить» месяцы за секунды и проверить,
вспомнит ли Джарвис факт через полгода.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Текущее время, секунды Unix (UTC)."""


class SystemClock:
    def now(self) -> float:
        return time.time()


@dataclass
class FakeClock:
    t: float = field(default_factory=lambda: datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc).timestamp())

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float = 0, *, minutes: float = 0, hours: float = 0, days: float = 0) -> None:
        self.t += seconds + minutes * 60 + hours * 3600 + days * 86400

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self.t = dt.timestamp()
