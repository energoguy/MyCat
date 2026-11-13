"""The focus timer: a stretch of work, then a short break. Pure clock arithmetic.

It does not run in circles: after a break you start the next focus yourself.
"""
from __future__ import annotations

import math
from typing import Optional


class Focus:
    def __init__(self):
        self.phase: Optional[str] = None  # None, "focus" or "break"
        self.since = 0.0
        self.until = 0.0

    def start(self, now: float, minutes: float) -> None:
        self.phase, self.since, self.until = "focus", now, now + minutes * 60

    def start_break(self, now: float, minutes: float) -> None:
        self.phase, self.since, self.until = "break", now, now + minutes * 60

    def stop(self) -> None:
        self.phase = None

    def tick(self, now: float) -> Optional[str]:
        """'focus_done' or 'break_done' at the moment a phase runs out, else None."""
        if self.phase is None or now < self.until:
            return None
        ended, self.phase = self.phase, None
        return ended + "_done"

    @property
    def focusing(self) -> bool:
        return self.phase == "focus"

    @property
    def on_break(self) -> bool:
        return self.phase == "break"

    def progress(self, now: float) -> float:
        if self.phase is None or self.until <= self.since:
            return 0.0
        return min(1.0, max(0.0, (now - self.since) / (self.until - self.since)))

    def minutes_left(self, now: float) -> int:
        """Rounded up, so it says "1 min left" until the very end, never 0."""
        return max(1, math.ceil((self.until - now) / 60)) if self.phase else 0

    def minutes_run(self, now: float) -> int:
        return int((min(now, self.until) - self.since) // 60) if self.phase else 0
