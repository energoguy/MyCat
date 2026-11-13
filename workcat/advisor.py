"""'What should I do now?' answered from what the cat knows, with no AI model involved.

Every idea comes from a fact: a task that is due, a stretch without a pause, a routine
whose time it is, the place you usually go to next. They are weighed against each other
and the best few are offered. The same list is handed to the chat AI, so it starts from
facts as well.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from .i18n import T
from .scene import WORK
from .tracker import slot_label


@dataclass
class Facts:
    now: float
    tasks: tuple = ()  # open tasks, as the store gives them
    goals: tuple = ()  # today's goals that are still open
    place_id: str = ""
    place_name: str = ""
    category: str = "other"
    streak_s: float = 0.0  # worked since the last real pause
    break_after_s: float = 0.0  # 0: never suggest a break
    focusing: bool = False
    on_break: bool = False
    focus_count: int = 0
    focus_min: int = 25
    active_s: float = 0.0
    routines: tuple = ()  # (place id, name, slot) whose usual time is now
    next_place: Optional[tuple] = None  # (place id, name) you usually go to after this one
    usual_end: Optional[float] = None  # the hour you usually wrap up
    energy: int = 100
    music: Optional[dict] = None  # what you usually play here, when nothing is playing


@dataclass(frozen=True)
class Idea:
    key: str
    text: str
    button: str = ""
    action: tuple = ()  # ("tasks",), ("break",), ("focus",), ("open", place id) or ("play", play)
    weight: int = 0


def ideas(f: Facts, limit: int = 3) -> list:
    """The best things to do now, strongest first. Never empty."""
    out: list = []
    clock = dt.datetime.fromtimestamp(f.now)
    hour = clock.hour + clock.minute / 60

    timed = sorted((t for t in f.tasks if t.get("due") and not t.get("place")), key=lambda t: t["due"])
    for task in timed[:2]:
        when = dt.datetime.fromtimestamp(task["due"]).strftime("%H:%M")
        if task["due"] <= f.now:
            out.append(Idea("task", T('"{text}" was due at {time}.', text=task["text"], time=when), T("Open tasks"), ("tasks",), 100))
        elif task["due"] - f.now <= 45 * 60:
            out.append(Idea("task", T('"{text}" is due at {time}.', text=task["text"], time=when), T("Open tasks"), ("tasks",), 90))

    if f.goals:  # what you said matters today comes before the rest of the list
        out.append(Idea("goal", T('Your goal for today: "{text}".', text=f.goals[0]["text"]), T("Open tasks"), ("tasks",), 80))

    wants_break = bool(f.break_after_s) and f.streak_s >= f.break_after_s and not f.on_break and not f.focusing
    if wants_break:
        out.append(Idea("break", T("You have worked {n} minutes without a pause.", n=int(f.streak_s // 60)), T("Take a break"), ("break",), 85))

    for place, name, slot in f.routines[:1]:
        out.append(Idea("routine:" + place, T("You usually open {name} around {time}.", name=name, time=slot_label(slot)), T("Open {name}", name=name), ("open", place), 70))

    if f.next_place and not any(idea.action == ("open", f.next_place[0]) for idea in out):
        out.append(Idea("next:" + f.next_place[0], T("After {here} you usually go to {name}.", here=f.place_name, name=f.next_place[1]), T("Open {name}", name=f.next_place[1]), ("open", f.next_place[0]), 55))

    if not f.focusing and not f.on_break and not wants_break and f.category in WORK:
        if f.focus_count == 0 and f.active_s >= 30 * 60:
            out.append(Idea("focus", T("No focus round yet today. {n} quiet minutes?", n=f.focus_min), T("Start focus"), ("focus",), 50))
        elif f.focus_count:
            out.append(Idea("focus", T("Another focus round? That would be number {n}.", n=f.focus_count + 1), T("Start focus"), ("focus",), 32))

    untimed = [t for t in f.tasks if not t.get("due") and not t.get("place")]
    if untimed:
        out.append(Idea("list", T('Next on your list: "{text}".', text=untimed[0]["text"]), T("Open tasks"), ("tasks",), 45))

    if f.usual_end is not None and hour >= f.usual_end + 0.5 and f.active_s >= 3 * 3600:
        out.append(Idea("wrap", T("You usually wrap up around {time}. Maybe call it a day?", time=slot_label(int(f.usual_end * 4))), weight=40))

    if f.energy < 35 and not wants_break and not f.on_break:
        out.append(Idea("energy", T("I am running low, and I think you are too. A short break?"), T("Take a break"), ("break",), 36))

    if f.music:
        out.append(Idea("music", T("In {place} you usually have {who} on.", place=f.place_name, who=f.music["who"]), T("Play it"), ("play", f.music), 30))

    out.sort(key=lambda idea: -idea.weight)
    picked: list = []
    for idea in out:  # one idea per action: two "open tasks" say the same thing
        if not any(idea.action and idea.action == other.action for other in picked):
            picked.append(idea)
    if not picked:
        picked.append(Idea("none", T("Nothing is pressing. Keep going, or take five and come back fresh.")))
    return picked[:limit]
