"""The cat's small talk. Rare by design: a work companion that chatters is a distraction."""
from __future__ import annotations

import random

from .i18n import N_, T

GREETINGS = {
    "morning": (N_("Good morning, {name} here."), N_("Morning! {name} is on duty."), N_("Good morning. Let's make today a tidy one.")),
    "afternoon": (N_("Good afternoon! {name} reporting in."), N_("Afternoon. Ready when you are.")),
    "evening": (N_("Good evening. A quiet shift, then."), N_("Evening! {name} is here.")),
    "night": (N_("Working late? I'll keep you company."), N_("Night shift. I'll stay close.")),
}

CHAT = {
    "code": (
        N_("One small step that works beats a big one that almost does."),
        N_("Name it well and half the bug is gone."),
        N_("Stuck? Explain it to me out loud. I'm a very good listener."),
        N_("Run it before you trust it."),
        N_("Future you will read this code. Be kind to them."),
        N_("If it's hard to test, it's telling you something."),
    ),
    "office": (
        N_("Hardest thing first? Then the rest of the day is downhill."),
        N_("A short email is a kind email."),
        N_("One thing at a time. I'm watching the tabs."),
        N_("If it takes two minutes, do it now."),
        N_("Meetings end faster when they start with the question."),
        N_("Save. I always say save."),
    ),
    "design": (
        N_("Step back and squint. Still good?"),
        N_("Empty space isn't empty. It's rest."),
        N_("Make it clear first, pretty second."),
        N_("Two typefaces are plenty. Three is a party."),
        N_("Zoom out before you zoom in again."),
    ),
    "study": (
        N_("Read a page, then tell me what it said."),
        N_("Twenty minutes of real attention beats two hours of almost."),
        N_("If you can teach it to a cat, you know it."),
        N_("Write the question down before you look up the answer."),
        N_("Sleep is when it sticks. Don't trade it away."),
    ),
    "any": (
        N_("A sip of water?"),
        N_("Shoulders down. Jaw unclenched."),
        N_("Look at something far away for a moment."),
        N_("I believe in you. Also in snacks."),
        N_("You're doing fine. I checked."),
        N_("Feet on the floor, back straight. There."),
        N_("Small progress is still progress."),
    ),
}

PURRS = (N_("Purr."), N_("More of that, please."), N_("Right there. Yes."), N_("Best part of my day."), N_("Okay, back to work. Both of us."))

TITLES = {
    "code": N_("Senior Purr-grammer"),
    "office": N_("Chief Paperwork Officer"),
    "design": N_("Art Director"),
    "study": N_("Honour Student"),
    "comms": N_("Head of Meow-tings"),
    "ai": N_("Prompt Whisperer"),
    "media": N_("House DJ"),
    "browser": N_("Head of Research"),
    "social": N_("Community Manager"),
    "game": N_("Quality Tester"),
}
PLAIN_TITLE = N_("Desk Companion")


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def greeting(hour: int, name: str) -> str:
    return T(random.choice(GREETINGS[part_of_day(hour)]), name=name)


def chat(category: str) -> str:
    return T(random.choice(CHAT.get(category, ()) + CHAT["any"]))


def purr() -> str:
    return T(random.choice(PURRS))


def job_title(category: str) -> str:
    return T(TITLES.get(category, PLAIN_TITLE))
