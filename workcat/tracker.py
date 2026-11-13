"""Keeps count of where your working time goes, and how long you have gone without a pause.

Every few seconds the app tells it: how long since the last key or mouse move, and which
place is in front. Time counts only while you are actually there. Nothing here knows what
you type or what is on the screen.
"""
from __future__ import annotations

import datetime as dt

from .scene import PAUSED_AFTER

SLOT_MIN = 15
REAL_PAUSE = 180  # this long without input is a break, not a thought


def day_of(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def slot_of(ts: float) -> int:
    t = dt.datetime.fromtimestamp(ts)
    return (t.hour * 60 + t.minute) // SLOT_MIN


def slot_label(slot: int) -> str:
    minutes = int(round(slot * SLOT_MIN))
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


class Tracker:
    def __init__(self, store, learn: bool = True):
        self.store = store
        self.learn = learn
        self.pending: dict = {}  # (day, slot, place id) -> seconds not yet written
        self.known: dict = {}  # place id -> Place already saved this run
        self.categories = {key: row["category"] for key, row in store.places().items() if row["custom"]}
        self.streak = 0.0  # seconds worked since the last real pause
        self.pause = 0.0  # length of the pause going on now
        self.place = None
        self.place_since = 0.0
        self.last = None

    def category(self, place) -> str:
        """The category of a place: yours if you changed it, else the built-in guess."""
        return self.categories.get(place.id, place.category) if place else "other"

    def sample(self, now: float, idle: float, place, away: bool = False) -> dict:
        """Account for the time since the previous sample. Returns what just happened:
        {'returned': seconds away} after a real pause, {'moved': place} on a new place."""
        happened: dict = {}
        step = 0.0 if self.last is None else min(max(now - self.last, 0.0), 30.0)
        self.last = now
        active = not away and idle < PAUSED_AFTER and place is not None
        if active:
            if self.pause >= REAL_PAUSE:
                happened["returned"] = self.pause
            self.pause = 0.0
            self.streak += step
            if place.id != (self.place.id if self.place else None):
                before = self.place
                if self.learn and before is not None and now - self.place_since >= 60 and "system" not in (self.category(before), self.category(place)):
                    self.store.add_move(before.id, place.id)  # for "after this you usually open that"
                self.place = place
                self.place_since = now
                happened["moved"] = place
            if self.learn and step and self.category(place) != "system":
                key = (day_of(now), slot_of(now), place.id)
                self.pending[key] = self.pending.get(key, 0.0) + step
                if place.id not in self.known:
                    self.known[place.id] = place
                    self.store.see_place(place.id, place.name, place.category, place.path, int(now))
        else:
            self.pause += step
            if self.pause >= REAL_PAUSE and self.streak:
                if self.streak >= 600:
                    self.store.log("break", {"after": int(self.streak)}, ts=now)
                self.streak = 0.0
        return happened

    def flush(self) -> None:
        if self.pending:
            self.store.add_usage(self.pending)
            self.pending = {}

    def forget(self) -> None:
        self.pending = {}
        self.known = {}
        self.categories = {}

    # ------------------------------------------------------------------ reading back

    def usage(self, first_day: str, last_day: str) -> dict:
        """Saved time plus what is still pending: day -> place -> slot -> seconds."""
        data = self.store.usage(first_day, last_day)
        for (day, slot, place), seconds in self.pending.items():
            if first_day <= day <= last_day:
                slots = data.setdefault(day, {}).setdefault(place, {})
                slots[slot] = slots.get(slot, 0) + seconds
        return data

    def day_totals(self, day: str) -> dict:
        """place -> seconds for one day."""
        return {place: sum(slots.values()) for place, slots in self.usage(day, day).get(day, {}).items()}

    def recent_places(self, now: float, minutes: int = 45) -> set:
        """Places used for at least a minute within the last `minutes`."""
        day = day_of(now)
        first = slot_of(now) - minutes // SLOT_MIN
        totals: dict = {}
        for place, slots in self.usage(day, day).get(day, {}).items():
            for slot, seconds in slots.items():
                if slot >= first:
                    totals[place] = totals.get(place, 0) + seconds
        return {place for place, seconds in totals.items() if seconds >= 60}
