"""What the cat learns from your days.

Plain counting, on this computer, over what the tracker saved: no network, no model.
Two kinds of habit come out of it:

  routines   "on workdays you start Excel around 09:30"
  listening  "around 21:00 you usually have music on, mostly this artist"

Everything takes its data as arguments and returns plain values, so it can be tested with
made-up days. The app turns the results into words and decides when to speak.

`usage` everywhere is: day ("2026-11-12") -> place id -> slot (quarter hour of the day,
0..95) -> seconds.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass

SLOTS = 96
FRESH_START = 300  # seconds in half an hour that count as "started using it"
STILL_WARM = 120  # seconds in the hour before that mean it was not a fresh start
NEAR = 2  # slots: starts within half an hour of each other are the same habit


def is_weekend(day: str) -> bool:
    return dt.date.fromisoformat(day).weekday() >= 5


def week_of(day: str) -> list:
    """The seven days, Monday first, of the week a day is in."""
    date = dt.date.fromisoformat(day)
    monday = date - dt.timedelta(days=date.weekday())
    return [(monday + dt.timedelta(days=i)).isoformat() for i in range(7)]


def per_day(usage: dict, days: list) -> list:
    """Seconds at the computer on each of `days`, in their order."""
    return [sum(sum(slots.values()) for slots in usage.get(day, {}).values()) for day in days]


def comparable_days(usage: dict, today: str, limit: int = 10, least: int = 1800) -> list:
    """Recent days of the same kind as today (workday or weekend) on which you were at
    the computer for at least half an hour, newest first. Today itself is left out."""
    kind = is_weekend(today)
    days = []
    for day in sorted(usage, reverse=True):
        if day >= today or is_weekend(day) != kind:
            continue
        if sum(sum(slots.values()) for slots in usage[day].values()) >= least:
            days.append(day)
    return days[:limit]


def session_starts(slots: dict) -> list:
    """The quarter hours at which a place was picked up after an hour without it."""
    starts = []
    for slot in sorted(slots):
        if slots[slot] + slots.get(slot + 1, 0) < FRESH_START:
            continue
        if sum(slots.get(slot - back, 0) for back in range(1, 5)) >= STILL_WARM:
            continue
        starts.append(slot)
    return starts


@dataclass(frozen=True)
class Routine:
    place: str
    slot: int  # the usual quarter hour
    seen: int  # on how many of the compared days
    days: int

    @property
    def share(self) -> float:
        return self.seen / self.days if self.days else 0.0


def find_routines(usage: dict, days: list, least_days: int = 3, share: float = 0.6, skip=()) -> list:
    """Places you start at about the same time on most comparable days."""
    if len(days) < least_days:
        return []
    need = max(least_days, math.ceil(share * len(days)))
    places = {place for day in days for place in usage.get(day, {})}
    found = []
    for place in sorted(places):
        if place in skip:
            continue
        left = {day: set(session_starts(usage.get(day, {}).get(place, {}))) for day in days}
        while True:
            best_slot, best_hits = -1, []
            for slot in range(SLOTS):
                hits = [min(left[d], key=lambda s: abs(s - slot)) for d in days if any(abs(s - slot) <= NEAR for s in left[d])]
                if len(hits) > len(best_hits) or (hits and len(hits) == len(best_hits) and _spread(hits) < _spread(best_hits)):
                    best_slot, best_hits = slot, hits
            if len(best_hits) < need:
                break
            centre = int(round(statistics.median(best_hits)))
            found.append(Routine(place, centre, len(best_hits), len(days)))
            for day in days:  # these starts are explained now
                left[day] = {s for s in left[day] if abs(s - best_slot) > NEAR * 2}
    found.sort(key=lambda r: (r.slot, r.place))
    return found


def _spread(values: list) -> float:
    return max(values) - min(values) if values else math.inf


def due_routines(routines: list, minute_of_day: int, recent: set) -> list:
    """Routines whose usual time is now, for places you have not touched lately.
    "Now" is from five minutes before the usual time to half an hour after."""
    out = []
    for routine in routines:
        usual = routine.slot * 15
        if usual - 5 <= minute_of_day <= usual + 30 and routine.place not in recent:
            out.append(routine)
    out.sort(key=lambda r: -r.share)
    return out


def typical_hours(usage: dict, days: list):
    """(usual first slot, usual last slot) of a day at the computer, or None."""
    firsts, lasts = [], []
    for day in days:
        per_slot: dict = {}
        for slots in usage.get(day, {}).values():
            for slot, seconds in slots.items():
                per_slot[slot] = per_slot.get(slot, 0) + seconds
        busy = sorted(slot for slot, seconds in per_slot.items() if seconds >= 300)
        if busy:
            firsts.append(busy[0])
            lasts.append(busy[-1] + 1)
    if len(firsts) < 3:
        return None
    return int(statistics.median(firsts)), int(statistics.median(lasts))


def next_place(moves: dict, least: int = 4, share: float = 0.4):
    """Where you usually go straight after a place, from counts of where you went:
    the favourite, if you went there at least four times and four times in ten."""
    total = sum(moves.values())
    if not total:
        return None
    place = max(moves, key=lambda p: moves[p])
    return place if moves[place] >= least and moves[place] / total >= share else None


def own_stretch(stretches: list, least: int = 8):
    """How long you usually work before you pause by yourself, in seconds: the middle
    one of your recent stretches. None until there are enough to say."""
    recent = [s for s in stretches[-30:] if s >= 600]
    return statistics.median(recent) if len(recent) >= least else None


EARLY = 1.15  # the reminder comes when you have gone this much past your usual stretch


def break_after(setting_min: int, stretch, adaptive: bool = True) -> float:
    """Seconds of work after which a stretch is suggested. Your own rhythm can bring the
    reminder forward (never below 25 minutes), it never pushes it past your setting."""
    if not setting_min:
        return 0.0
    limit = setting_min * 60.0
    if adaptive and stretch:
        return min(limit, max(25 * 60.0, stretch * EARLY))
    return limit


def totals(usage: dict, days: list) -> dict:
    """place -> seconds over the given days."""
    out: dict = {}
    for day in days:
        for place, slots in usage.get(day, {}).items():
            out[place] = out.get(place, 0) + sum(slots.values())
    return out


# --------------------------------------------------------------------------- listening

def who(play: dict) -> str:
    """Whose it is: the artist or channel; a bare title if nothing else is known."""
    return (play.get("artist") or play.get("title") or "").strip()


def listening_days(plays: list, days: list, hour: int, least: int = 480) -> int:
    """On how many of `days` something played for at least eight minutes in that hour."""
    wanted = set(days)
    per_day: dict = {}
    for play in plays:
        start = dt.datetime.fromtimestamp(play["started"])
        day = start.strftime("%Y-%m-%d")
        if day in wanted and start.hour == hour:
            per_day[day] = per_day.get(day, 0) + (play["ended"] - play["started"])
    return sum(1 for seconds in per_day.values() if seconds >= least)


def favourite(plays: list, now: float, hour=None, fade: float = 0.93):
    """What you play most, recent days counting more. With `hour`, only what played
    within an hour of that time of day. Returns the play to offer plus its weight."""
    weight: dict = {}
    latest: dict = {}
    for play in plays:
        name = who(play)
        if not name:
            continue
        start = dt.datetime.fromtimestamp(play["started"])
        if hour is not None and min((start.hour - hour) % 24, (hour - start.hour) % 24) > 1:
            continue
        age_days = max(0.0, (now - play["started"]) / 86400)
        weight[name] = weight.get(name, 0.0) + (play["ended"] - play["started"]) * fade**age_days
        if name not in latest or play["started"] > latest[name]["started"]:
            latest[name] = play
    if not weight:
        return None
    name = max(weight, key=lambda n: weight[n])
    return dict(latest[name], who=name, weight=weight[name])


def on_repeat(plays: list, now: float, days: int = 7, least_plays: int = 5):
    """The artist you came back to most this week, if it was at least five times."""
    counts: dict = {}
    latest: dict = {}
    for play in plays:
        if not play.get("artist") or now - play["started"] > days * 86400:
            continue
        name = play["artist"].strip()
        counts[name] = counts.get(name, 0) + 1
        latest[name] = play
    if not counts:
        return None
    name = max(counts, key=lambda n: counts[n])
    if counts[name] < least_plays:
        return None
    return dict(latest[name], who=name, plays=counts[name])


def during(plays: list, spans: list) -> list:
    """The plays that started inside any of the (start, end) spans."""
    return [p for p in plays if any(start <= p["started"] < end for start, end in spans)]


def place_music(plays: list, usage: dict, place: str, now: float, least_days: int = 3):
    """What you usually have on while you are in one place ("in VS Code: lo-fi").

    A play belongs to a place if you spent at least five minutes of the quarter hour it
    started in there. It has to have happened on three different days to be a habit.
    """
    there = []
    days = set()
    for play in plays:
        start = dt.datetime.fromtimestamp(play["started"])
        day = start.strftime("%Y-%m-%d")
        slot = (start.hour * 60 + start.minute) // 15
        if usage.get(day, {}).get(place, {}).get(slot, 0) >= 300:
            there.append(play)
            days.add(day)
    if len(days) < least_days:
        return None
    return favourite(there, now)
