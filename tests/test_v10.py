"""Tests for what 0.10 added: what the cat brings up by itself (a task or a goal, meals,
that it is late), the weather, and what kind of day it is.

The weather service is a pretend one on this computer: nothing here asks the real one."""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v7 import Scripted  # noqa: E402
from workcat import days, extras, nudges, weather  # noqa: E402
from workcat.store import DEFAULTS, Store  # noqa: E402

FRIDAY = dt.date(2026, 11, 13)


def at(hour: int, minute: int = 0, day: dt.date = FRIDAY) -> float:
    return dt.datetime.combine(day, dt.time(hour, minute)).timestamp()


def forecast(code: int = 3, hours=(), now: float = 0.0, **more) -> dict:
    return {"asked": "tashkent", "city": "Tashkent", "at": now or time.time(), "temp": 9, "code": code, "high": 12, "low": 4, "hours": [list(hour) for hour in hours], **more}


class DaysTest(unittest.TestCase):
    def test_days_with_a_fixed_date(self):
        self.assertEqual(days.names(dt.date(2026, 11, 13)), ["World Kindness Day"])
        self.assertEqual(days.names(dt.date(2026, 8, 8)), ["International Cat Day"])
        self.assertEqual(days.names(dt.date(2026, 11, 14)), [])

    def test_days_that_move(self):
        self.assertEqual(days.nth_weekday(2026, 10, 4, 1), dt.date(2026, 10, 2))  # the first Friday of October
        self.assertEqual(days.nth_weekday(2026, 7, 4, -1), dt.date(2026, 7, 31))  # the last Friday of July
        self.assertEqual(days.nth_weekday(2026, 12, 6, -1), dt.date(2026, 12, 27))
        self.assertIn("World Smile Day", days.names(dt.date(2026, 10, 2)))
        self.assertIn("Programmers' Day", days.names(dt.date(2026, 9, 13)))
        self.assertIn("Programmers' Day", days.names(dt.date(2028, 9, 12)))  # a leap year: the 256th day comes a date earlier
        self.assertIn("World Laughter Day", days.names(dt.date(2026, 5, 3)))

    def test_every_name_has_its_translations(self):
        for code in ("ru", "uz"):
            table = json.loads((ROOT / "workcat" / "lang" / f"{code}.json").read_text(encoding="utf-8"))
            for name in list(days.FIXED.values()) + [name for _when, name in days.MOVING]:
                self.assertIn(name, table, (code, name))

    def test_the_persons_own_dates(self):
        rows = [{"name": "Dilnoza's birthday", "month": 11, "day": 14}, {"name": "Our day", "month": 11, "day": 13}, {"name": "Leap", "month": 2, "day": 29}]
        self.assertEqual(days.own(rows, FRIDAY), [("Our day", "today"), ("Dilnoza's birthday", "tomorrow")])
        self.assertEqual(days.own(rows, dt.date(2026, 11, 15)), [])
        self.assertEqual(days.own(rows, dt.date(2027, 2, 28)), [("Leap", "today")])  # no 29th that year
        self.assertEqual(days.own(rows, dt.date(2028, 2, 28)), [("Leap", "tomorrow")])
        self.assertEqual(days.coming(rows, FRIDAY, within=7), [("Our day", 0), ("Dilnoza's birthday", 1)])


class Service(BaseHTTPRequestHandler):
    """Answers like Open-Meteo does: a place for a name, a forecast for a place."""

    seen: list = []
    known = True
    places = None  # when set, like the real one: {(name, language asked in): (its name there, its country)}, and nothing else is found

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        Service.seen.append((url.path, query))
        if url.path == "/place" and Service.places is not None:
            hit = Service.places.get((query["name"], query["language"]))
            body = {"results": [{"name": hit[0], "country": hit[1], "latitude": 41.26, "longitude": 69.22}]} if hit else {}
        elif url.path == "/place":
            body = {"results": [{"name": "Tashkent", "country": "Uzbekistan", "country_code": "UZ", "latitude": 41.26, "longitude": 69.22}]} if Service.known else {}
        else:
            body = {
                "current": {"time": "2026-11-13T09:00", "temperature_2m": 8.6, "weather_code": 3},
                "daily": {"temperature_2m_max": [12.4, 10.0], "temperature_2m_min": [3.5, 2.0]},
                "hourly": {"time": ["2026-11-13T14:00", "2026-11-13T15:00"], "precipitation_probability": [20, 80], "weather_code": [3, 61]},
            }
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class WeatherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
        cls.address = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Service.seen, Service.known, Service.places = [], True, None

    def test_asked_for_a_city_and_nothing_else(self):
        found = weather.fetch("Tashkent", self.address + "/place", self.address + "/forecast")
        self.assertEqual((found["city"], found["asked"], found["temp"], found["code"], found["high"], found["low"]), ("Tashkent", "tashkent", 9, 3, 12, 4))
        self.assertEqual(found["hours"][1], ["2026-11-13T15:00", 80, 61])
        (_path, place), (_path2, asked) = Service.seen
        self.assertEqual(place["name"], "Tashkent")
        self.assertEqual(set(asked), {"latitude", "longitude", "current", "hourly", "daily", "timezone", "forecast_days"})  # a place on the map, and what is wanted of it
        self.assertEqual((asked["latitude"], asked["longitude"]), ("41.26", "69.22"))
        self.assertEqual(found["place"], "Tashkent, Uzbekistan")  # what the service found, for the person to check

    def test_how_a_city_is_asked_for(self):
        self.assertEqual(weather.spellings("Ташкент"), [("Ташкент", "ru"), ("Tashkent", "uz")])  # never in English: that finds nothing, or something else
        self.assertEqual(weather.spellings(" Самарқанд "), [("Самарқанд", "ru"), ("Samarqand", "uz")])
        self.assertEqual(weather.spellings("Tashkent"), [("Tashkent", "en"), ("Tashkent", "uz")])
        self.assertEqual(weather.spellings("Tashkent", "ru"), [("Tashkent", "ru"), ("Tashkent", "en"), ("Tashkent", "uz")])
        self.assertEqual(weather.spellings("New   York", "uz"), [("New York", "uz"), ("New York", "en")])

    def test_a_city_typed_in_cyrillic_letters(self):
        Service.places = {("Ташкент", "ru"): ("Ташкент", "Узбекистан"), ("Toshkent", "uz"): ("Toshkent", "Oʻzbekiston")}
        place, sky = self.address + "/place", self.address + "/forecast"
        found = weather.fetch("Ташкент", place, sky, shown="Ташкент")
        self.assertEqual((found["city"], found["place"], found["asked"]), ("Ташкент", "Ташкент, Узбекистан", "ташкент"))
        self.assertEqual((Service.seen[0][1]["name"], Service.seen[0][1]["language"]), ("Ташкент", "ru"))
        Service.seen = []
        found = weather.fetch("Тошкент", place, sky, shown="Тошкент")  # the Uzbek spelling, which Russian does not have
        self.assertEqual([(query["name"], query["language"]) for path, query in Service.seen if path == "/place"], [("Тошкент", "ru"), ("Toshkent", "uz")])
        self.assertEqual((found["city"], found["place"]), ("Тошкент", "Toshkent, Oʻzbekiston"))
        with self.assertRaises(weather.NoSuchCity):
            weather.fetch("Қаердадир", place, sky)

    def test_a_guessed_city_is_named_in_the_cats_language(self):
        Service.places = {("Tashkent", "ru"): ("Ташкент", "Узбекистан"), ("Tashkent", "uz"): ("Toshkent", "Oʻzbekiston"), ("New York", "uz"): ("New York", "AQSH")}
        place, sky = self.address + "/place", self.address + "/forecast"
        self.assertEqual(weather.fetch("Tashkent", place, sky, language="ru")["city"], "Ташкент")
        self.assertEqual(weather.fetch("Tashkent", place, sky, language="uz")["city"], "Тошкент")  # the service's Uzbek is in Latin letters, the cat's in Cyrillic
        self.assertEqual(weather.fetch("New York", place, sky, language="uz")["city"], "New York")  # no rule makes that Cyrillic: left as it is

    def test_the_name_is_sent_once(self):
        place, sky = self.address + "/place", self.address + "/forecast"
        first = weather.fetch("Tashkent", place, sky)
        Service.seen = []
        again = weather.fetch("Tashkent", place, sky, spot=first["spot"])
        self.assertEqual([path for path, _query in Service.seen], ["/forecast"])  # the place is remembered: only where it is goes out
        self.assertEqual((again["city"], again["place"]), (first["city"], first["place"]))

    def test_a_city_nobody_knows_and_no_connection(self):
        Service.known = False
        with self.assertRaises(ValueError):
            weather.fetch("Qwertyville", self.address + "/place", self.address + "/forecast")
        with self.assertRaises(OSError):
            weather.fetch("Tashkent", "http://127.0.0.1:1/place", "http://127.0.0.1:1/forecast", timeout=2)

    def test_what_is_coming(self):
        nine = dt.datetime(2026, 11, 13, 9, 0)
        rain = forecast(hours=[("2026-11-13T10:00", 20, 3), ("2026-11-13T15:00", 80, 61)])
        self.assertEqual(weather.coming(rain, nine), ("rain", "15:00"))
        self.assertIsNone(weather.coming(rain, nine, within=3.0))  # not within three hours
        self.assertEqual(weather.coming(rain, dt.datetime(2026, 11, 13, 12, 30), within=3.0), ("rain", "15:00"))
        self.assertEqual(weather.coming(forecast(hours=[("2026-11-13T11:00", 70, 73)]), nine), ("snow", "11:00"))
        self.assertIsNone(weather.coming(forecast(hours=[("2026-11-13T11:00", 30, 61)]), nine))  # not likely enough
        self.assertIsNone(weather.coming(forecast(code=61, hours=[("2026-11-13T11:00", 90, 61)]), nine))  # it rains already
        self.assertIsNone(weather.coming(forecast(hours=[("2026-11-13T08:00", 90, 61)]), nine))  # that hour is past

    def test_as_the_cat_says_it(self):
        nine = dt.datetime(2026, 11, 13, 9, 0)
        self.assertEqual(weather.line(forecast(), nine), "Tashkent: 9 °C, cloudy. Today between 4 and 12 °C.")
        said = weather.line(forecast(hours=[("2026-11-13T15:00", 80, 61)]), nine)
        self.assertTrue(said.endswith("Rain is likely around 15:00: an umbrella would be wise."), said)
        self.assertIn("I have fur", weather.line(forecast(low=-9), nine))
        self.assertIn("drink water", weather.line(forecast(high=38), nine))

    def test_a_guess_where_no_city_was_typed(self):
        real = weather.region
        try:
            weather.region = lambda: "UZ"
            self.assertEqual(weather.guess_city(), "Tashkent")
            weather.region = lambda: "ZZ"
            self.assertEqual(weather.guess_city(), "")  # no guess: then nothing is asked until a city is typed
        finally:
            weather.region = real


class Nudged(Scripted):
    """The cat of the scripts test, with what the reminders look at."""

    def __init__(self, store):
        super().__init__(store)
        self.settings["first_run_done"] = True
        self.said: set = set()
        self.now = at(9, 0)
        self.day_started = at(8, 30)
        self.buttons: list = []
        self.opened: list = []
        self.finished: list = []
        self.not_found: list = []
        self.inbox = __import__("queue").Queue()
        self.voice = type("Voice", (), {"say": lambda _self, text, buttons=(), **kind: (self.spoken.append(text), self.buttons.append(list(buttons)))})()
        self.weather = weather.Weather(self)

    def clock(self) -> float:
        return self.now

    def say_once(self, key: str) -> bool:
        fresh = key not in self.said
        self.said.add(key)
        return fresh

    def open_goals(self) -> None:
        self.opened.append("goals")

    def city_unknown(self, city: str) -> None:
        self.not_found.append(city)

    def open_panel(self, tab: str = "today") -> None:
        self.opened.append(tab)

    def complete_task(self, number: int) -> None:
        self.finished.append(number)


class NudgesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.cat = Nudged(self.store)
        self.cat.settings.update(weather=False, nudge_days=False, nudge_meals=False, nudge_late=False, nudge_goals="off")
        self.nudges = nudges.Nudges(self.cat, at(8, 30))

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def due(self, hour: int, minute: int = 0, day: dt.date = FRIDAY) -> bool:
        self.cat.now = at(hour, minute, day)
        return self.nudges.due(self.cat.now)

    def press(self, label: str) -> None:
        next(pressed for text, pressed in self.cat.buttons[-1] if text == label)()

    def test_what_comes_set_as_it_was_asked_for(self):
        for key, value in (("nudge_goals", "sometimes"), ("nudge_meals", True), ("nudge_late", True), ("late_hour", 23), ("nudge_days", True), ("weather", True), ("weather_city", "")):
            self.assertEqual(DEFAULTS[key], value, key)

    def test_all_switched_off_it_says_nothing(self):
        self.store.add_task("Send the weekly report")
        for hour in (9, 13, 16, 23):
            self.assertFalse(self.due(hour, 30), hour)
        self.assertEqual(self.cat.spoken, [])

    def test_nobody_there_nothing_said(self):
        self.cat.settings["nudge_meals"] = True
        self.cat.last_idle = 600.0
        self.assertFalse(self.due(9, 0))
        self.cat.last_idle = 0.0
        self.assertTrue(self.due(9, 0))

    def test_breakfast_and_lunch(self):
        self.cat.settings["nudge_meals"] = True
        self.assertFalse(self.due(8, 33))  # only just sat down
        self.assertTrue(self.due(8, 40))
        self.assertIn(self.cat.spoken[-1], [line for line in nudges.BREAKFAST])
        self.assertFalse(self.due(8, 50))  # once
        self.press("Not yet")
        self.assertFalse(self.due(9, 10))
        self.assertTrue(self.due(9, 21))  # half an hour after "Not yet" (pressed at 8:50), once more
        self.assertEqual(self.cat.spoken[-1], nudges.AGAIN["breakfast"])
        self.press("Not yet")
        self.assertFalse(self.due(9, 50))  # and then it lets go after all
        self.assertFalse(self.due(12, 59))
        self.assertTrue(self.due(13, 5))
        self.assertIn(self.cat.spoken[-1], nudges.LUNCH)
        self.press("Yes")
        self.assertIn(self.cat.spoken[-1], nudges.FED)
        self.assertFalse(self.due(13, 40))

    def test_breakfast_is_not_asked_about_at_noon(self):
        self.cat.settings["nudge_meals"] = True
        self.cat.day_started = at(11, 0)  # a late start: breakfast is past, lunch is not yet
        self.assertFalse(self.due(11, 30))
        self.assertTrue(self.due(13, 0))

    def test_that_it_is_late_three_times_a_night_at_most(self):
        self.cat.settings["nudge_late"] = True
        self.assertFalse(self.due(22, 59))
        self.assertTrue(self.due(23, 1))
        self.assertIn("23:01", self.cat.spoken[-1])
        self.assertFalse(self.due(23, 30))  # not again for forty minutes
        self.assertTrue(self.due(23, 42))
        self.press("Half an hour more")
        self.assertFalse(self.due(23, 59))
        saturday = FRIDAY + dt.timedelta(days=1)
        self.assertTrue(self.due(0, 13, saturday))  # after midnight it is still the same night
        self.assertFalse(self.due(1, 30, saturday))  # three were said
        self.assertFalse(self.due(9, 0, saturday))  # and by day it is not late
        self.assertTrue(self.due(23, 5, saturday))  # another night
        self.cat.settings["late_hour"] = 21
        self.nudges.late_next = 0.0
        self.assertTrue(self.due(21, 30, FRIDAY + dt.timedelta(days=2)))

    def test_a_task_or_a_goal_with_a_joke(self):
        self.cat.settings["nudge_goals"] = "sometimes"
        self.assertFalse(self.due(8, 40))  # not right after the start
        task = self.store.add_task("Send the weekly report")
        self.store.add_task("Call the bank", due=int(at(15)))  # this one has its own time
        self.assertTrue(self.due(9, 20))
        self.assertIn('"Send the weekly report"', self.cat.spoken[-1])
        self.assertEqual([label for label, _ in self.cat.buttons[-1]], ["Done", "Open tasks", "Later"])
        self.press("Done")
        self.assertEqual(self.cat.finished, [task])
        self.assertFalse(self.due(9, 50))  # the next one in about two hours
        self.store.delete_task(task)
        goal = self.store.add_long_goal("week", extras.period("week", FRIDAY), "Finish the yearly report")
        self.store.set_long_goal(goal, 40)
        self.assertTrue(self.due(11, 45))
        said = self.cat.spoken[-1]
        self.assertIn('"Finish the yearly report"', said)
        self.assertIn("40 %", said)
        self.assertNotIn("{", said)
        self.press("Habits and goals")
        self.assertEqual(self.cat.opened, ["goals"])
        self.store.set_long_goal(goal, 100)  # done: nothing left to bring up (the bank call has its time)
        self.assertFalse(self.due(14, 30))
        self.assertEqual(self.store.get("nudged"), None)  # on a Friday the cat does not start about goals for a week nearly over

    def test_a_week_without_goals_is_mentioned_once_early_in_it(self):
        self.cat.settings["nudge_goals"] = "often"
        monday = dt.date(2026, 11, 16)
        self.cat.day_started = at(8, 30, monday)
        self.nudges = nudges.Nudges(self.cat, at(8, 30, monday))
        self.assertTrue(self.due(9, 20, monday))
        self.assertEqual(self.cat.spoken[-1], nudges.NO_GOALS)
        self.assertFalse(self.due(11, 0, monday))
        self.assertFalse(self.due(9, 30, monday + dt.timedelta(days=1)))

    def test_what_is_left_of_a_week_a_month_a_year(self):
        self.assertEqual([nudges.days_left(span, FRIDAY) for span in ("week", "month", "year")], [3, 18, 49])
        self.assertEqual(nudges.days_left("week", dt.date(2026, 11, 15)), 1)  # Sunday: today is all that is left
        self.assertEqual(nudges.days_left("month", dt.date(2026, 11, 30)), 1)

    def test_every_line_keeps_its_blanks_in_each_language(self):
        import re

        blanks = lambda text: sorted(re.findall(r"\{(\w+)\}", text))  # noqa: E731
        for code in ("ru", "uz"):
            table = json.loads((ROOT / "workcat" / "lang" / f"{code}.json").read_text(encoding="utf-8"))
            for line in nudges.TASK + nudges.WEEK + nudges.MONTH + nudges.YEAR + nudges.LATE + nudges.BREAKFAST + nudges.LUNCH + nudges.FED + nudges.DAY_TAILS + (nudges.NO_GOALS,) + tuple(nudges.AGAIN.values()):
                self.assertEqual(blanks(table[line]), blanks(line), (code, line))

    def test_the_morning_what_day_it_is_and_the_weather(self):
        self.cat.settings.update(nudge_days=True, weather=True, weather_city="Tashkent")
        self.store.add_own_day("Dilnoza's birthday", 11, 14)
        self.cat.weather.data = forecast(hours=[("2026-11-13T11:00", 80, 61)], now=at(8, 31))
        self.assertFalse(self.due(8, 31))  # give the person a moment after they sat down
        self.assertTrue(self.due(8, 33))
        said = self.cat.spoken[-1]
        self.assertIn("Today is World Kindness Day.", said)
        self.assertIn("Tomorrow: Dilnoza's birthday.", said)
        self.assertIn("Tashkent: 9 °C, cloudy.", said)
        self.assertIn("Rain is likely around 11:00", said)
        self.assertIn("Open-Meteo", said)  # the first time it says where this comes from
        self.assertFalse(self.due(8, 50))  # once a morning; and the rain was in it, so it is not said again
        self.assertEqual(len(self.cat.spoken), 1)
        self.cat.said.clear()
        self.assertTrue(self.due(8, 55))
        self.assertNotIn("Open-Meteo", self.cat.spoken[-1])  # ... and only the first time

    def test_weather_that_comes_after_the_morning_is_told_once_by_itself(self):
        self.cat.settings.update(nudge_days=True, weather=True, weather_city="Tashkent")
        self.assertTrue(self.due(8, 33))  # what day it is; there is no weather yet (no connection, say)
        self.assertNotIn("°C", self.cat.spoken[-1])
        self.assertFalse(self.due(9, 0))
        self.cat.weather.data = forecast(now=at(9, 29), place="Tashkent, Uzbekistan")
        self.assertTrue(self.due(9, 30))
        self.assertIn("Tashkent: 9 °C, cloudy.", self.cat.spoken[-1])
        self.assertIn("for Tashkent, Uzbekistan.", self.cat.spoken[-1])  # the first time: what the service found for the name
        self.assertFalse(self.due(10, 0))
        self.assertEqual(len(self.cat.spoken), 2)

    def test_the_morning_waits_while_the_weather_is_on_its_way(self):
        self.cat.settings.update(nudge_days=True, weather=True, weather_city="Tashkent")
        self.cat.weather.fetching = True
        self.assertFalse(self.due(8, 33))
        self.assertFalse(self.due(8, 35))
        self.cat.weather.fetching, self.cat.weather.data = False, forecast(now=at(8, 35))
        self.assertTrue(self.due(8, 36))
        self.assertIn("World Kindness Day", self.cat.spoken[-1])
        self.assertIn("Tashkent: 9 °C", self.cat.spoken[-1])  # one bubble for both
        self.assertFalse(self.due(8, 50))

    def test_but_the_morning_does_not_wait_for_ever(self):
        self.cat.settings.update(nudge_days=True, weather=True, weather_city="Tashkent")
        self.cat.weather.fetching = True
        self.assertFalse(self.due(8, 33))
        self.assertFalse(self.due(8, 37))
        self.assertTrue(self.due(8, 39))
        self.assertNotIn("°C", self.cat.spoken[-1])

    def test_a_city_the_service_does_not_know(self):
        asked = []
        real = weather.fetch

        def no_such(city, *_a, **_more):
            asked.append(city)
            if city == "Qwertyville":
                raise weather.NoSuchCity(city)
            return forecast(now=time.time())

        weather.fetch = no_such
        try:
            sky = self.cat.weather
            sky.data = None
            self.cat.settings.update(weather=True, weather_city="Qwertyville")
            sky.tick(time.time())
            _kind, found = self.cat.inbox.get(timeout=5)
            sky.arrived(found)
            self.assertEqual(self.cat.not_found, ["Qwertyville"])  # the person is told
            sky.tick(time.time())
            self.assertEqual((asked, sky.fetching), (["Qwertyville"], False))  # ... and it is not asked for again and again
            self.cat.settings["weather_city"] = "Tashkent"  # another one is typed
            self.cat.said.add("weather")
            sky.tick(time.time())
            self.assertNotIn("weather", self.cat.said)  # its weather is told once it is here, also if today's was told already
            _kind, found = self.cat.inbox.get(timeout=5)
            sky.arrived(found)
            self.assertEqual((asked, self.cat.not_found), (["Qwertyville", "Tashkent"], ["Qwertyville"]))
        finally:
            weather.fetch = real

    def test_rain_that_comes_later_in_the_day(self):
        self.cat.settings.update(weather=True, weather_city="Tashkent")
        self.cat.weather.data = forecast(hours=[("2026-11-13T15:00", 80, 61)], now=at(8, 31))
        self.assertTrue(self.due(8, 33))  # the morning line (rain at 15:00 is in it as "likely around")
        self.assertFalse(self.due(10, 0))  # five hours off: not yet
        self.cat.weather.data["at"] = at(12, 0)
        self.assertTrue(self.due(12, 30))
        self.assertEqual(self.cat.spoken[-1], "Tashkent: Rain is likely around 15:00: an umbrella would be wise.")
        self.assertFalse(self.due(13, 0))

    def test_no_weather_without_the_switch_or_with_an_old_forecast(self):
        self.cat.settings.update(weather=False, weather_city="Tashkent", nudge_days=False)
        self.cat.weather.data = forecast(now=at(8, 31))
        self.assertFalse(self.due(8, 40))
        self.cat.settings["weather"] = True
        self.cat.said.clear()
        self.cat.weather.data = forecast(now=at(8, 31) - 9 * 3600)  # from last night
        self.cat.day_started = at(8, 0)
        self.assertFalse(self.due(8, 40))  # nothing fresh came in the first minutes: the morning passes without it
        self.assertEqual(self.cat.spoken, [])
        self.cat.settings["weather_city"] = "Samarkand"  # another city than the forecast is for
        self.cat.weather.data = forecast(now=at(8, 39))
        self.assertIsNone(self.cat.weather.fresh(at(8, 40)))

    def test_the_forecast_is_asked_for_only_when_it_may_be(self):
        asked = []
        real = weather.fetch
        weather.fetch = lambda city, *a, **k: asked.append(city) or forecast(now=time.time())
        try:
            sky = self.cat.weather
            sky.data = None
            self.cat.settings.update(weather=False, weather_city="Tashkent")
            sky.tick(time.time())
            self.assertEqual((asked, sky.fetching), ([], False))  # switched off: nothing is asked
            self.cat.settings["weather"] = True
            self.cat.last_idle = 900.0
            sky.tick(time.time())
            self.assertEqual((asked, sky.fetching), ([], False))  # nobody at the computer: nothing is asked
            self.cat.last_idle = 0.0
            sky.tick(time.time())
            self.assertTrue(sky.fetching)
            kind, found = self.cat.inbox.get(timeout=5)
            self.assertEqual((kind, asked), ("weather", ["Tashkent"]))
            sky.arrived(found)
            self.assertEqual((sky.fetching, self.store.get("weather")["city"]), (False, "Tashkent"))
            sky.tick(time.time())
            self.assertEqual(len(asked), 1)  # fresh: not asked again for hours
            sky.arrived(None)  # no connection
            self.assertGreater(sky.next_try, time.time() + 600)
        finally:
            weather.fetch = real


class OwnDaysTest(unittest.TestCase):
    def test_kept_in_the_order_of_the_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.add_own_day("New flat", 12, 1)
            first = store.add_own_day("Dilnoza's birthday", 3, 14)
            store.add_own_day("Odd", 15, 40)  # out of range: kept inside the calendar
            self.assertEqual([(row["name"], row["month"], row["day"]) for row in store.own_days()], [("Dilnoza's birthday", 3, 14), ("New flat", 12, 1), ("Odd", 12, 31)])
            store.delete_own_day(first)
            self.assertEqual(len(store.own_days()), 2)
            store.close()


if __name__ == "__main__":
    unittest.main()
