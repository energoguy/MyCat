"""Tasks and reminders. Reading a time out of what you typed, and deciding what is due.

The time goes at the end, in English, Russian or Uzbek (Cyrillic or Latin letters):

    Call the bank at 15:30        Позвонить в банк в 15:30        Банкка қўнғироқ 15:30 да
    Stretch in 20 min             Размяться через 20 мин          Чигил ёзиш 20 дақиқадан кейин
    Lunch in half an hour         Обед через полчаса              Тушлик ярим соатдан кейин
    Send the report tomorrow 9:00 Отправить отчёт завтра 9:00     Ҳисобот юбориш эртага 9:00
    Stand-up at 9am               Планёрка в 9 утра               Мажлис соат 9 да

A bare "15:30" at the end works in any language.
"""
from __future__ import annotations

import datetime as dt
import re

from .i18n import N_, T

RETRY_AFTER = 15 * 60  # a reminder nobody answered comes back after this long
MAX_TRIES = 3
NOTE_GAP = 2 * 3600  # an "every time" note shows at most this often

WEEKDAYS = (N_("Mon"), N_("Tue"), N_("Wed"), N_("Thu"), N_("Fri"), N_("Sat"), N_("Sun"))
_HOUR_UNITS = ("h", "ч", "соат", "soat")  # h, hr, hour; ч, час; соат; soat
# Words that say which half of the day: "в 5 вечера", "кечқурун соат 5 да".
_HALVES = {
    "am": "am", "pm": "pm",
    "утра": "am", "ночи": "am", "дня": "pm", "вечера": "pm",
    "эрталаб": "am", "ertalab": "am", "кечқурун": "pm", "kechqurun": "pm",
}


def _hour(groups: dict) -> int:
    hour = int(groups["h"])
    half = _HALVES.get((groups.get("half") or groups.get("part") or groups.get("early") or "").lower())
    if half:
        hour = hour % 12 + (12 if half == "pm" else 0)
    return hour


def _at(now: dt.datetime, hour: int, minute: int, days: int = 0):
    if hour >= 24 or minute >= 60:
        return None
    return (now + dt.timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _after(m, now):
    """'in 20 min', 'in an hour', 'через 2 часа', 'через час', '20 дақиқадан кейин'."""
    groups = m.groupdict()
    amount = int(groups.get("n") or 1)
    hours = groups["unit"].lower().startswith(_HOUR_UNITS)
    return now + (dt.timedelta(hours=amount) if hours else dt.timedelta(minutes=amount))


def _half_hour(m, now):
    """'in half an hour', 'через полчаса', 'ярим соатдан кейин'."""
    return now + dt.timedelta(minutes=30)


def _next_day(m, now):
    """'tomorrow', 'tomorrow 9:00', 'завтра в 9', 'эртага соат 9:00 да'. No time means 09:00."""
    groups = m.groupdict()
    return _at(now, _hour(groups) if groups.get("h") else 9, int(groups.get("m") or 0), days=1)


def _clock(m, now):
    """'at 15:30', '15:30', 'at 9am', 'в 15:30', '15:30 да'. A time already past means tomorrow."""
    groups = m.groupdict()
    when = _at(now, _hour(groups), int(groups.get("m") or 0))
    if when is not None and when <= now:
        when += dt.timedelta(days=1)
    return when


def _form(pattern: str, read) -> tuple:
    return re.compile(r"\s+" + pattern + r"\s*$", re.I), read


_H, _HM, _H_M = r"(?P<h>\d{1,2})", r"(?P<h>\d{1,2}):(?P<m>\d{2})", r"(?P<h>\d{1,2})\.(?P<m>\d{2})"
_H_OR_HM = r"(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?"
_AT_WORD = r"(?:at|в|соат|soat)"  # English, Russian, Uzbek
_RU_HOURS = r"(?:час(?:а|ов)?|ч\.?)"
_RU_PART = r"(?P<part>утра|дня|вечера|ночи)"
_UZ_EARLY = r"(?:(?P<early>эрталаб|ertalab|кечқурун|kechqurun)\s+)?"  # said before the time
_UZ_AT = r"(?:да|da)"  # "15:30 да"
_UZ_AFTER = r"(?:дан|dan)?\s+(?:кейин|keyin|сўнг|so'ng)"
_UZ_UNIT = r"(?P<unit>дақиқа|daqiqa|минут|minut|соат|soat)"
_MARK = r"(?:(?P<half>am|pm)|" + _UZ_AT + "|" + _RU_PART + ")"  # what may follow a time

# Tried in this order: "tomorrow 9:00" must be read whole before "9:00" is.
_FORMS = (
    # after a while
    _form(r"in\s+(?:(?P<n>\d{1,3})\s*|(?:an?|one)\s+)(?P<unit>m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", _after),
    _form(r"in\s+half\s+an\s+hour", _half_hour),
    _form(r"через\s+(?:(?P<n>\d{1,3})\s*)?(?P<unit>м|мин|минут[уы]?|ч|час(?:а|ов)?)\.?", _after),
    _form(r"через\s+полчаса", _half_hour),
    _form(r"(?:(?P<n>\d{1,3})\s*|(?:бир|bir)\s+)" + _UZ_UNIT + _UZ_AFTER, _after),
    _form(r"(?:ярим|yarim)\s+(?:соат|soat)" + _UZ_AFTER, _half_hour),
    # tomorrow
    _form(r"tomorrow(?:\s+(?:at\s+)?" + _H_OR_HM + r"\s*(?P<half>am|pm)?)?", _next_day),
    _form(r"завтра(?:\s+(?:в\s+)?" + _H_OR_HM + r"(?:\s*" + _RU_HOURS + r")?(?:\s+" + _RU_PART + r")?)?", _next_day),
    _form(r"(?:эртага|ertaga)(?:\s+" + _UZ_EARLY + r"(?:(?:соат|soat)\s+)?" + _H_OR_HM + r"(?:\s*" + _UZ_AT + r")?)?", _next_day),
    # a time today. "9.30" counts only next to a time word: "version 3.10" is not ten past three
    _form(_UZ_EARLY + r"(?:" + _AT_WORD + r"\s+)?" + _HM + r"\s*" + _MARK + "?", _clock),
    _form(_UZ_EARLY + _AT_WORD + r"\s+" + _H_M + r"\s*" + _MARK + "?", _clock),
    _form(_H_M + r"\s*" + _MARK, _clock),
    # the hour alone, when the words around it leave no doubt
    _form(r"(?:at\s+)?" + _H + r"\s*(?P<half>am|pm)", _clock),  # 9am, at 9 pm
    _form(r"в\s+" + _H + r"\s*(?:" + _RU_HOURS + r"\s*)?" + _RU_PART, _clock),  # в 9 утра, в 5 часов вечера
    _form(r"в\s+" + _H + r"\s*" + _RU_HOURS, _clock),  # в 9 часов, в 14 ч
    _form(_UZ_EARLY + r"(?:соат|soat)\s+" + _H + r"\s*" + _UZ_AT, _clock),  # соат 9 да, кечқурун соат 5 да
)
_APOSTROPHES = re.compile("[ʻʼ’‘`]")  # the many signs people type for the one in so'ng


def parse_quick(text: str, now: dt.datetime) -> tuple:
    """Split 'what at when' into (what, when). `when` is None if no time was written."""
    text = text.strip()
    probe = _APOSTROPHES.sub("'", text)  # same length, so positions match
    for pattern, read in _FORMS:
        m = pattern.search(probe)
        if m:
            when = read(m, now)
            if when is not None:
                return text[: m.start()].strip(), when
    return text, None


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})")


def parse_when(when: str, now: dt.datetime):
    """A time written by the chat AI in one of the forms it is told to use:
    '', 'HH:MM', 'today HH:MM', 'tomorrow HH:MM', 'in N min', 'in N hours', 'YYYY-MM-DD HH:MM'.
    Returns None when there is no time or it cannot be read."""
    when = (when or "").strip().lower()
    if not when:
        return None
    m = _ISO.match(when)
    if m:
        try:
            return dt.datetime(*(int(g) for g in m.groups()))
        except ValueError:
            return None
    if when.startswith("today"):
        when = when[5:].strip()
    return parse_quick("x " + when, now)[1]


def due_label(due, now: dt.datetime) -> str:
    """'15:30', 'tomorrow 09:00', 'Mon 09:00' or 'late' for a task's time."""
    if not due:
        return ""
    when = dt.datetime.fromtimestamp(due)
    if when < now:
        return T("late")
    days = (when.date() - now.date()).days
    clock = when.strftime("%H:%M")
    if days == 0:
        return clock
    if days == 1:
        return T("tomorrow {time}", time=clock)
    return T(WEEKDAYS[when.weekday()]) + " " + clock


def due_tasks(tasks: list, now: float) -> list:
    """Timed tasks whose moment has come and that were not just shown."""
    out = []
    for task in tasks:
        if task["done"] or not task["due"] or task["place"] or task["due"] > now:
            continue
        if task["tries"] >= MAX_TRIES:
            continue
        if task["shown"] and now - task["shown"] < RETRY_AFTER:
            continue
        out.append(task)
    return out


def notes_for(tasks: list, place_id: str, now: float) -> list:
    """Notes tied to a place ("remind me here") that should show on arriving there."""
    out = []
    for task in tasks:
        if task["done"] or task["place"] != place_id:
            continue
        if task["shown"] and now - task["shown"] < (NOTE_GAP if task["repeat"] else 20 * 60):
            continue
        out.append(task)
    return out
