"""The cat's mood and condition, worked out from the day so far.

Nothing here is random. The cat is tired because you have both been at it for nine hours,
proud because three focus rounds are done, worried because nobody has paused in ninety
minutes. Its energy follows the clock and how the day is going, so looking at the cat
tells you something true about your own day.

Pure functions over plain numbers: the app gathers the facts, this decides how the cat feels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .i18n import N_, T, duration


@dataclass
class Day:
    """What is known about today, right now."""
    hour: float  # time of day, 0..24
    weekend: bool = False
    active_s: float = 0.0  # at the computer today
    streak_s: float = 0.0  # worked since the last real pause
    idle_s: float = 0.0
    focusing: bool = False
    on_break: bool = False
    focus_count: int = 0
    breaks: int = 0
    tasks_done: int = 0
    tasks_late: int = 0
    pets: int = 0
    since_pet: Optional[float] = None  # seconds since it was last petted
    since_play: Optional[float] = None  # seconds since you last played together
    since_win: Optional[float] = None  # seconds since a task or a focus round was finished
    music: bool = False
    usual_end: Optional[float] = None  # the hour you usually wrap up
    since_start: Optional[float] = None  # seconds since today's first activity
    break_after_s: float = 50 * 60  # when a stretch is suggested


@dataclass(frozen=True)
class Condition:
    mood: str  # one of sprites.MOODS
    why: str  # one short sentence, in the cat's words
    energy: int  # 0..100


MOOD_WORDS = {
    "content": N_("Content"), "happy": N_("Happy"), "fresh": N_("Fresh"), "playful": N_("Playful"), "proud": N_("Proud"),
    "cozy": N_("Cosy"), "focused": N_("Focused"), "sleepy": N_("Sleepy"), "tired": N_("Tired"), "worried": N_("Worried"),
    "lonely": N_("A bit lonely"),
}

# The cat's own daily rhythm: (hour, energy). Bright in the morning, drowsy at night.
_RHYTHM = ((0, 22), (5, 25), (7, 78), (10, 95), (13, 86), (15, 76), (18, 66), (21, 46), (23, 28), (24, 22))


def _rhythm(hour: float) -> float:
    hour = hour % 24
    for (h0, e0), (h1, e1) in zip(_RHYTHM, _RHYTHM[1:]):
        if h0 <= hour <= h1:
            return e0 + (e1 - e0) * (hour - h0) / (h1 - h0)
    return 22.0


def energy(day: Day) -> int:
    """0..100. The clock sets the level; long stretches and long days drain it,
    pauses give some of it back."""
    value = _rhythm(day.hour)
    value -= min(28.0, day.streak_s / 60 * 0.28)  # 90 minutes without a pause costs 25
    value -= min(25.0, max(0.0, day.active_s / 3600 - 6) * 5)  # every hour past six costs 5
    value += min(12.0, day.breaks * 3)
    if day.music:
        value += 3
    if day.since_pet is not None and day.since_pet < 600:
        value += 4
    return int(round(min(100.0, max(5.0, value))))


def energy_word(value: int) -> str:
    if value >= 75:
        return T("full of energy")
    if value >= 50:
        return T("doing fine")
    if value >= 30:
        return T("getting tired")
    return T("running low")


def condition(day: Day) -> Condition:
    """How the cat feels, and why. The first rule that fits wins."""
    level = energy(day)
    night = day.hour >= 23 or day.hour < 5
    streak_min = int(day.streak_s // 60)

    def feel(mood: str, why: str) -> Condition:
        return Condition(mood, why, level)

    if day.focusing:
        return feel("focused", T("In the zone with you."))
    if day.idle_s >= 300:
        return feel("sleepy", T("Napping until you are back."))
    if day.since_play is not None and day.since_play < 300:
        return feel("playful", T("That was fun!"))
    if day.since_pet is not None and day.since_pet < 180:
        return feel("happy", T("That was nice."))
    if day.since_win is not None and day.since_win < 600:
        return feel("proud", T("We got something done."))
    if night:
        return feel("sleepy", T("It is late. I am sleepy, and I think you are too."))
    if day.streak_s >= max(90 * 60, 1.5 * day.break_after_s):
        return feel("worried", T("No pause for {n} minutes. I worry a little.", n=streak_min))
    if day.active_s >= 9 * 3600:
        return feel("tired", T("Long day: {time} at the computer.", time=duration(day.active_s)))
    if day.usual_end is not None and day.hour >= day.usual_end + 1.5 and day.active_s >= 4 * 3600:
        return feel("tired", T("You are usually done by now."))
    if day.tasks_late:
        return feel("worried", T("Something on your list is late."))
    if day.on_break:
        return feel("playful", T("Break time is my favourite time."))
    if day.focus_count >= 3 or day.tasks_done >= 3:
        if day.focus_count >= 3:
            return feel("proud", T("{n} focus rounds today!", n=day.focus_count))
        return feel("proud", T("{n} tasks done today!", n=day.tasks_done))
    if day.music:
        return feel("cozy", T("Good music, good company."))
    if day.pets == 0 and day.active_s >= 3 * 3600 and day.hour >= 14:
        return feel("lonely", T("You have not said hello today."))
    if level < 30:
        return feel("tired", T("My battery is low."))
    if day.since_start is not None and day.since_start < 3600 and day.hour < 12:
        return feel("fresh", T("Fresh start. Let's go."))
    if day.weekend:
        return feel("playful", T("Weekend mood."))
    if day.pets >= 3 or day.breaks >= 2:
        return feel("happy", T("A good day so far."))
    return feel("content", T("All is well."))


# --------------------------------------------------------------------------- the bond

BOND_STEPS = (0, 15, 50, 120, 250, 500)
BOND_NAMES = (N_("New friends"), N_("Getting close"), N_("Good friends"), N_("Close friends"), N_("Best friends"), N_("Family"))


def bond_level(points: int) -> int:
    """0..5: how close you two are. It only ever grows."""
    return max(i for i, need in enumerate(BOND_STEPS) if points >= need)


def bond_name(points: int) -> str:
    return T(BOND_NAMES[bond_level(points)])


def bond_progress(points: int) -> float:
    """0..1 on the way to the next level (1 at the top)."""
    level = bond_level(points)
    if level == len(BOND_STEPS) - 1:
        return 1.0
    low, high = BOND_STEPS[level], BOND_STEPS[level + 1]
    return (points - low) / (high - low)
