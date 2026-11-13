"""What the cat brings up by itself, now and then: a task or a goal (with a joke), that it
is late, breakfast and lunch, and in the morning what kind of day it is and the weather.

Each kind has its switch in Settings. All of it keeps the rules the cat's other reminders
keep: `due` is only asked when the cat may speak at all (not in a call, a focus round or
something full screen, not while its bubble is up), and it says one thing at a time.

The lines are plain sentences, several for each kind, so they are easy to change in the
language files.
"""
from __future__ import annotations

import calendar
import datetime as dt
import random

from . import days, weather
from .i18n import N_, T

EVERY = {"sometimes": (100, 140), "often": (50, 70)}  # minutes between two reminders of a task or a goal
LATE_MOST = 3  # times a night that "it is late" is said
LATE_GAP = 40 * 60

TASK = (
    N_('"{task}" is still on your list. It looks at me every time I walk by.'),
    N_('A small reminder with big eyes: "{task}".'),
    N_('I sat on your list and "{task}" poked me. Do it, please.'),
    N_('"{task}" is still waiting. I would do it myself, but nobody gave me thumbs.'),
    N_('Tasks do not finish themselves. I watched "{task}" all night to be sure.'),
    N_('Finish "{task}" and I will purr. That offer is serious.'),
)
WEEK = (
    N_('Days left this week: {days}. "{goal}" is at {n} %. I believe in you. Mostly.'),
    N_('Weekly goal check: "{goal}", {n} %. I would help, but I have paws.'),
    N_('"{goal}" is at {n} % and the week has {days} days left. I counted them on my toes.'),
    N_('Psst. "{goal}": {n} %. I am not judging. I am a cat: I judge silently.'),
    N_('If "{goal}" were my food bowl, it would be {n} % full. I would be worried.'),
    N_('This week\'s goal "{goal}" is waiting at {n} %. It asked about you.'),
)
MONTH = (
    N_('Days left this month: {days}. "{goal}" is at {n} %. No pressure. A little pressure.'),
    N_('Monthly goal "{goal}": {n} %. I have slept through bigger problems, but still.'),
    N_('"{goal}" stands at {n} % this month. Shall we push it a little, or shall I push something off the table?'),
    N_('Your goal "{goal}" called. It is at {n} % and feels lonely.'),
    N_('Month check: "{goal}", {n} %. I am keeping score, and I am bad with numbers, so hurry.'),
)
YEAR = (
    N_('Your goal for the year, "{goal}", is at {n} %. Days left this year: {days}. I did the sums so you need not.'),
    N_('"{goal}": {n} % of the way. A year is long, says the cat who sleeps sixteen hours a day.'),
    N_('Big goal check: "{goal}", {n} %. Even I catch the red dot in the end.'),
    N_('The year has {days} days left for "{goal}" ({n} %). I will ask again. I have nine lives of patience.'),
)
NO_GOALS = N_("You have no goal for this week yet. Even a small one counts. Mine is: a nap.")
LATE = (
    N_("It is {time}. The screen can wait until tomorrow; your sleep cannot."),
    N_("{time}. Even cats go to bed at some point. So I have heard."),
    N_("It is {time} and you are still here. I am closing one eye as a hint."),
    N_("{time}. Tomorrow's you would like a word with tonight's you. About sleep."),
    N_("It is {time}. The work will still be here tomorrow. I will guard it."),
)
BREAKFAST = (
    N_("Good morning! Had breakfast yet?"),
    N_("Breakfast check: have you eaten? I have. Twice."),
    N_("A brain runs on breakfast. Mine runs on naps, but yours: breakfast. Had some?"),
)
LUNCH = (
    N_("Lunch time! Have you eaten?"),
    N_("It is about lunch time. Your keyboard is not food. Have you eaten?"),
    N_("Lunch check. I can hear your stomach from here. Eaten yet?"),
)
AGAIN = {
    "breakfast": N_("About that breakfast: still not? I am not letting this go."),
    "lunch": N_("And lunch? I asked half an hour ago. I forget nothing."),
}
FED = (N_("Good. A fed human is a happy human."), N_("Excellent. I am proud of you, and a little hungry now."))
DAY_TAILS = (
    N_("I will celebrate by sitting here. Very festively."),
    N_("I marked it by not knocking anything off your desk. So far."),
    N_("Any excuse for a treat, I say."),
    N_("I looked it up so you can sound clever today."),
)


def days_left(span: str, day: dt.date) -> int:
    """Days that are left of the week, the month or the year, today included."""
    if span == "week":
        return 7 - day.weekday()
    if span == "month":
        return calendar.monthrange(day.year, day.month)[1] - day.day + 1
    return (dt.date(day.year, 12, 31) - day).days + 1


class Nudges:
    def __init__(self, app, now: float):
        self.app = app
        self.next_goal = now + random.uniform(25, 45) * 60  # not right after the start
        self.again: dict = {}  # "breakfast" | "lunch" -> when to ask once more
        self.late_night = ""  # the night the count below belongs to
        self.late_said = 0
        self.late_next = 0.0
        self.waiting_since = 0.0  # since when the morning's lines have waited for the weather

    # ------------------------------------------------------------------ what is asked every half minute

    def due(self, now: float) -> bool:
        """Say one thing, if the moment has come for one. True if something was said."""
        app = self.app
        if not app.settings["first_run_done"] or app.last_idle >= 120:  # nobody there to hear it
            return False
        clock = dt.datetime.fromtimestamp(now)
        return self.morning(now, clock) or self.meal(now, clock) or self.late(now, clock) or self.sky(now, clock) or self.rain(now, clock) or self.goal(now, clock)

    # ------------------------------------------------------------------ the morning: what day it is, and the weather

    def morning_words(self, now: float, clock: dt.datetime) -> list:
        """The lines of the morning: the kind of day, the person's own dates, the weather."""
        app, s = self.app, self.app.settings
        said = []
        if s["nudge_days"]:
            today = clock.date()
            for name in days.names(today)[:1]:
                said.append(T("Today is {day}.", day=T(name)) + " " + T(random.choice(DAY_TAILS)))
            for name, when in days.own(app.store.own_days(), today):
                said.append(T("Today: {name}. Do not forget!", name=name) if when == "today" else T("Tomorrow: {name}. I am telling you today so that you look prepared.", name=name))
        data = app.weather.fresh(now)
        if data is not None:
            said += self.weather_words(data, clock)
        return said

    def weather_words(self, data: dict, clock: dt.datetime) -> list:
        """The weather as the cat says it. The first time for a city, also where that
        comes from, what the service found for the name, and where the switch is."""
        app = self.app
        app.say_once("weather")
        said = [weather.line(data, clock)]
        if app.store.get("weather_told") != data.get("asked"):
            app.store.put("weather_told", data.get("asked"))
            said.append(T("(I looked that up online, at Open-Meteo, for {city}. Settings has the switch and the city.)", city=data.get("place") or data["city"]))
        return said

    def morning(self, now: float, clock: dt.datetime) -> bool:
        app = self.app
        if app.day_started is None or now - app.day_started < 90 or "morning" in app.said:
            return False
        # the weather may be on its way this very moment: wait for it, but not for ever
        if app.settings["weather"] and app.weather.fetching and app.weather.fresh(now) is None:
            self.waiting_since = self.waiting_since or now
            if now - self.waiting_since < 5 * 60:
                return False
        app.say_once("morning")
        said = self.morning_words(now, clock)
        data = app.weather.fresh(now)
        if data is not None and weather.coming(data, clock, within=3.0, chance=60):
            app.say_once("rain")  # it is in these lines already: not said again five minutes later
        if not said:
            return False
        app.voice.say("\n".join(said), kind="nudge", ttl=18 + 6 * len(said))
        return True

    def sky(self, now: float, clock: dt.datetime) -> bool:
        """The weather by itself, once: when it came only after the morning's lines (there
        was no connection then, or the switch or the city was set later in the day)."""
        app = self.app
        data = app.weather.fresh(now)
        if data is None or "morning" not in app.said or "weather" in app.said:
            return False
        said = self.weather_words(data, clock)
        if weather.coming(data, clock, within=3.0, chance=60):
            app.say_once("rain")  # it is in these lines already
        app.voice.say("\n".join(said), kind="nudge", ttl=18 + 6 * len(said))
        return True

    def rain(self, now: float, clock: dt.datetime) -> bool:
        """Later in the day: rain or snow that is coming within the next three hours."""
        app = self.app
        data = app.weather.fresh(now)
        if data is None or "morning" not in app.said or "rain" in app.said:
            return False
        ahead = weather.coming(data, clock, within=3.0, chance=60)
        if ahead is None:
            return False
        app.say_once("rain")
        text = T("Rain is likely around {time}: an umbrella would be wise.", time=ahead[1]) if ahead[0] == "rain" else T("Snow is likely around {time}. I will stay inside, thank you.", time=ahead[1])
        app.voice.say(f"{data['city']}: {text}", kind="nudge", ttl=18)
        return True

    # ------------------------------------------------------------------ breakfast and lunch

    def meal(self, now: float, clock: dt.datetime) -> bool:
        app, s = self.app, self.app.settings
        if not s["nudge_meals"] or app.day_started is None:
            return False
        hour = clock.hour + clock.minute / 60
        for meal, lines in (("breakfast", BREAKFAST), ("lunch", LUNCH)):
            if meal in self.again and now >= self.again[meal]:  # "not yet", half an hour ago
                del self.again[meal]
                self.ask(meal, T(AGAIN[meal]), again=False)
                return True
            if meal in app.said:
                continue
            at_breakfast = meal == "breakfast" and hour < s["breakfast_until"] and now - app.day_started >= 8 * 60
            at_lunch = meal == "lunch" and s["lunch_hour"] <= hour < s["lunch_hour"] + 2
            if at_breakfast or at_lunch:
                app.say_once(meal)
                self.ask(meal, T(random.choice(lines)), again=True)
                return True
        return False

    def ask(self, meal: str, text: str, again: bool) -> None:
        app = self.app

        def fed() -> None:
            self.again.pop(meal, None)
            app.voice.say(T(random.choice(FED)), kind="reply", ttl=5)

        def not_yet() -> None:
            if again:
                self.again[meal] = app.clock() + 30 * 60

        app.voice.say(text, [(T("Yes"), fed), (T("Not yet"), not_yet)], kind="nudge", ttl=30)

    # ------------------------------------------------------------------ late in the evening

    def late(self, now: float, clock: dt.datetime) -> bool:
        s = self.app.settings
        if not s["nudge_late"]:
            return False
        start = int(s["late_hour"])
        is_late = clock.hour >= start or clock.hour < 5 if start >= 12 else start <= clock.hour < 5
        night = (clock - dt.timedelta(hours=5)).date().isoformat()  # one night, also after midnight
        if night != self.late_night:
            self.late_night, self.late_said, self.late_next = night, 0, 0.0
        if not is_late or self.late_said >= LATE_MOST or now < self.late_next:
            return False
        self.late_said += 1
        self.late_next = now + LATE_GAP

        def more() -> None:
            self.late_next = self.app.clock() + 30 * 60

        self.app.voice.say(T(random.choice(LATE), time=clock.strftime("%H:%M")), [(T("Going"), lambda: None), (T("Half an hour more"), more)], kind="nudge", ttl=30)
        return True

    # ------------------------------------------------------------------ a task or a goal, with a joke

    def pick(self, clock: dt.datetime):
        """What to bring up: ("task", row) or ("week" | "month" | "year", goal), or None.
        A goal's turn comes more often when its time is running out."""
        from .extras import current_goals

        app = self.app
        today = clock.date()
        choices, weights = [], []
        tasks = [task for task in app.store.tasks() if not task.get("due")]  # those with a time are reminded of at their time
        if tasks:
            choices.append(("task", random.choice(tasks)))
            weights.append(3.0)
        for span, weight in (("week", 3.0), ("month", 2.0), ("year", 1.0)):
            goals = [goal for goal in current_goals(app.store, span, today) if goal["progress"] < 100]
            if goals:
                hurry = 2.0 if days_left(span, today) <= {"week": 3, "month": 7, "year": 30}[span] else 1.0
                choices.append((span, min(goals, key=lambda goal: (goal["progress"], random.random()))))
                weights.append(weight * hurry)
        return random.choices(choices, weights)[0] if choices else None

    def goal(self, now: float, clock: dt.datetime) -> bool:
        app = self.app
        how = app.settings["nudge_goals"]
        if how not in EVERY or now < self.next_goal:
            return False
        self.next_goal = now + random.uniform(*EVERY[how]) * 60
        picked = self.pick(clock)
        today = clock.date()
        if picked is None:
            week = f"no-goals:{today.isocalendar()[0]}-{today.isocalendar()[1]}"
            if app.store.get("nudged") == week or clock.weekday() > 2:  # said once, early in a week that has no goal
                return False
            app.store.put("nudged", week)
            app.voice.say(T(NO_GOALS), [(T("Habits and goals"), app.open_goals), (T("Later"), lambda: None)], kind="nudge", ttl=25)
            return True
        kind, row = picked
        if kind == "task":
            text = T(random.choice(TASK), task=row["text"])
            buttons = [(T("Done"), lambda: app.complete_task(row["id"])), (T("Open tasks"), lambda: app.open_panel("tasks")), (T("Later"), lambda: None)]
        else:
            lines = {"week": WEEK, "month": MONTH, "year": YEAR}[kind]
            text = T(random.choice(lines), goal=row["text"], n=row["progress"], days=days_left(kind, today))
            buttons = [(T("Habits and goals"), app.open_goals), (T("Later"), lambda: None)]
        app.voice.say(text, buttons, kind="nudge", ttl=30)
        return True
