"""What kind of day it is: well-known days of the year, and the person's own dates.

The list holds international days only, no country's holidays (that was the choice made
for it), with a few that are simply fun. Everything here is worked out on this computer.
"""
from __future__ import annotations

import datetime as dt

from .i18n import N_

# (month, day) -> what the day is called, as it stands in "Today is ...".
FIXED = {
    (1, 1): N_("New Year's Day"),
    (2, 14): N_("Valentine's Day"),
    (3, 8): N_("International Women's Day"),
    (3, 14): N_("Pi Day"),
    (3, 20): N_("the International Day of Happiness"),
    (3, 21): N_("the International Day of Nowruz"),
    (3, 22): N_("World Water Day"),
    (4, 1): N_("April Fools' Day"),
    (4, 7): N_("World Health Day"),
    (4, 12): N_("the International Day of Human Space Flight"),
    (4, 22): N_("Earth Day"),
    (4, 23): N_("World Book Day"),
    (4, 29): N_("International Dance Day"),
    (5, 1): N_("International Workers' Day"),
    (5, 15): N_("the International Day of Families"),
    (5, 21): N_("International Tea Day"),
    (6, 1): N_("International Children's Day"),
    (6, 3): N_("World Bicycle Day"),
    (6, 5): N_("World Environment Day"),
    (7, 7): N_("World Chocolate Day"),
    (7, 30): N_("the International Day of Friendship"),
    (8, 8): N_("International Cat Day"),
    (8, 12): N_("International Youth Day"),
    (8, 19): N_("World Photography Day"),
    (8, 26): N_("International Dog Day"),
    (9, 8): N_("International Literacy Day"),
    (9, 21): N_("the International Day of Peace"),
    (9, 27): N_("World Tourism Day"),
    (10, 1): N_("International Coffee Day"),
    (10, 4): N_("World Animal Day"),
    (10, 5): N_("World Teachers' Day"),
    (10, 10): N_("World Mental Health Day"),
    (10, 16): N_("World Food Day"),
    (11, 13): N_("World Kindness Day"),
    (11, 19): N_("International Men's Day"),
    (11, 21): N_("World Hello Day"),
    (12, 10): N_("Human Rights Day"),
    (12, 11): N_("International Mountain Day"),
    (12, 31): N_("New Year's Eve"),
}


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th Monday (weekday 0) ... Sunday (6) of a month; n = -1 for the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


# Days that fall on another date each year: (how to find it for a year, its name).
MOVING = (
    (lambda year: dt.date(year, 1, 1) + dt.timedelta(days=255), N_("Programmers' Day")),  # the 256th day
    (lambda year: nth_weekday(year, 5, 6, 1), N_("World Laughter Day")),  # the first Sunday of May
    (lambda year: nth_weekday(year, 7, 4, -1), N_("System Administrator Appreciation Day")),  # the last Friday of July
    (lambda year: nth_weekday(year, 10, 4, 1), N_("World Smile Day")),  # the first Friday of October
)


def names(day: dt.date) -> list:
    """What this day is known as (English; the caller puts it into the person's language)."""
    found = [FIXED[(day.month, day.day)]] if (day.month, day.day) in FIXED else []
    found += [name for when, name in MOVING if when(day.year) == day]
    return found


def own(rows: list, day: dt.date) -> list:
    """The person's own dates that fall on this day or the next: (name, "today" | "tomorrow").
    `rows` have 'name', 'month' and 'day'. One kept for 29 February is remembered on the
    28th in years that have no 29th."""
    def falls(row, on: dt.date) -> bool:
        month, number = int(row["month"]), int(row["day"])
        if (month, number) == (2, 29) and on.month == 2 and on.day == 28:
            return (on + dt.timedelta(days=1)).month == 3
        return (month, number) == (on.month, on.day)

    tomorrow = day + dt.timedelta(days=1)
    return [(row["name"], "today") for row in rows if falls(row, day)] + [(row["name"], "tomorrow") for row in rows if falls(row, tomorrow) and not falls(row, day)]


def coming(rows: list, day: dt.date, within: int = 14) -> list:
    """The person's own dates in the next days, nearest first: (name, days from now)."""
    found = []
    for ahead in range(within + 1):
        on = day + dt.timedelta(days=ahead)
        found += [(row["name"], ahead) for row in rows if (int(row["month"]), int(row["day"])) == (on.month, on.day)]
    return found
