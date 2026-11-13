"""What is going on at the desk right now, and how the cat dresses and behaves for it.

Scene is filled in by the app from the activity tracker; the cat only reads it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

AWAY_AFTER = 300  # seconds without input before the cat decides you left
PAUSED_AFTER = 60

WORK = frozenset({"code", "office", "design", "study"})


@dataclass
class Scene:
    category: str = "other"
    idle: float = 0.0  # seconds since the last key or mouse move
    focus: Optional[float] = None  # 0..1 while a focus session runs
    on_break: bool = False
    in_call: bool = False
    music: bool = False
    mood: str = "content"  # how the cat feels; see mood.py

    @property
    def away(self) -> bool:
        return self.idle >= AWAY_AFTER

    @property
    def paused(self) -> bool:
        return self.idle >= PAUSED_AFTER


@dataclass(frozen=True)
class Look:
    acc: Optional[str] = None  # what it wears on the head
    item: Optional[str] = None  # what it works with
    tie: bool = False
    accent: str = "blue"


LOOKS = {
    "code": Look("glasses", "laptop", False, "green"),
    "office": Look(None, "laptop", True, "blue"),
    "design": Look("beret", "easel", False, "orange"),
    "study": Look("gradcap", "book", False, "purple"),
    "media": Look("headphones", None, False, "purple"),
}


def look_of(scene: Scene) -> Look:
    base = LOOKS.get(scene.category, Look())
    acc = base.acc
    if scene.in_call:
        acc = "headset"
    elif scene.music and scene.category not in WORK:
        acc = "headphones"
    item = base.item or ("laptop" if scene.focus is not None else None)
    return Look(acc, item, base.tie, base.accent if base.item or base.acc else ("purple" if scene.music else "blue"))


def rest_anim(scene: Scene) -> str:
    """What the cat does while it stays where it is."""
    if scene.focus is not None:
        return "focus"
    if scene.away:
        return "sleep"
    if scene.on_break:
        return "listen" if scene.music else "sit"
    if scene.category in WORK and not scene.paused:
        return "work"
    if scene.music and not scene.in_call:
        return "listen"
    return "sit"
