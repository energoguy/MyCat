"""The weather for one city, from Open-Meteo (open-meteo.com): a free service that needs
no account and no key.

This is the one thing the cat fetches from the internet without being asked each time,
and it says so: on the welcome screen, in Settings (one switch turns it off, a field
holds the city), and the first time it tells the weather for a city. What is sent: the
city's name, to find where it is (once: the place is then remembered), and after that
only that place's coordinates, for the forecast. Nothing else, and only while somebody
is at the computer.

The city is the one typed in Settings, in Latin or in Cyrillic letters, or else a guess
from the region Windows is set to (its capital). The cat names the city with every
weather line, and the first time also what the service found for it, so that a wrong
guess or a wrong match shows at once.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from . import i18n, translit
from .i18n import N_, T

log = logging.getLogger("workcat")

PLACE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
KEEP = 3 * 3600  # seconds a forecast is used before it is asked for again
RETRY = 30 * 60  # ... and after a failure
AWAY = 10 * 60  # nobody touched the computer for this long: nobody to tell the weather to, so it is not asked

# The service's weather codes (WMO), as words.
SKY = {
    0: N_("clear"), 1: N_("mostly clear"), 2: N_("partly cloudy"), 3: N_("cloudy"), 45: N_("fog"), 48: N_("fog"),
    51: N_("drizzle"), 53: N_("drizzle"), 55: N_("drizzle"), 56: N_("freezing rain"), 57: N_("freezing rain"),
    61: N_("rain"), 63: N_("rain"), 65: N_("heavy rain"), 66: N_("freezing rain"), 67: N_("freezing rain"),
    71: N_("snow"), 73: N_("snow"), 75: N_("heavy snow"), 77: N_("snow"), 80: N_("rain showers"), 81: N_("rain showers"), 82: N_("heavy rain"),
    85: N_("snow showers"), 86: N_("snow showers"), 95: N_("a thunderstorm"), 96: N_("a thunderstorm"), 99: N_("a thunderstorm"),
}
SNOW = frozenset((71, 73, 75, 77, 85, 86))
RAIN = frozenset((51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99))

# Where no city was typed: the capital of the country Windows is set to.
CAPITALS = {
    "UZ": "Tashkent", "KZ": "Astana", "KG": "Bishkek", "TJ": "Dushanbe", "TM": "Ashgabat", "AZ": "Baku", "GE": "Tbilisi", "AM": "Yerevan",
    "RU": "Moscow", "BY": "Minsk", "UA": "Kyiv", "TR": "Ankara", "US": "Washington", "GB": "London", "DE": "Berlin", "FR": "Paris",
    "IT": "Rome", "ES": "Madrid", "PL": "Warsaw", "NL": "Amsterdam", "KR": "Seoul", "JP": "Tokyo", "CN": "Beijing", "IN": "New Delhi",
    "AE": "Abu Dhabi", "SA": "Riyadh", "EG": "Cairo", "CA": "Ottawa", "AU": "Canberra", "BR": "Brasilia",
}


class NoSuchCity(ValueError):
    """The service knows no place of that name."""


def region() -> str:
    """The country Windows is set to, as two letters ("UZ"), or ""."""
    try:
        name = ctypes.create_unicode_buffer(16)
        if ctypes.windll.kernel32.GetUserDefaultGeoName(name, 16):
            return name.value.upper()
    except (AttributeError, OSError):
        pass
    return ""


def guess_city() -> str:
    return CAPITALS.get(region(), "")


def _get(url: str, query: dict, timeout: float) -> dict:
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(query), headers={"User-Agent": "MyCat"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def spellings(city: str, language: str = "en") -> list:
    """How to ask the service where a city is: (name, language to ask in) pairs, the
    likeliest first. The service finds a name only in the language it is asked in, or by
    its English spelling: "Ташкент" asked for in English finds nothing, or something else
    that merely sounds alike. So a name in Cyrillic letters is asked for in Russian, then
    as Uzbek (which the service has in Latin letters); one in Latin letters in the cat's
    own language first, so that the name comes back in it."""
    name = " ".join(city.split())
    if _cyrillic(name):
        tries = [(name, "ru"), (translit.to_latin(name), "uz")]
    else:
        tries = [(name, language if language in ("ru", "uz") else "en"), (name, "en"), (name, "uz")]
    return list(dict.fromkeys(tries))


def find(city: str, language: str = "en", place: str = PLACE, timeout: float = 10.0) -> dict:
    """Where a city is, as the service knows it: its name and country there, and its
    place on the map. Raises NoSuchCity when no spelling finds one."""
    for name, asked_in in spellings(city, language):
        found = _get(place, {"name": name, "count": 1, "language": asked_in, "format": "json"}, timeout).get("results") or []
        if found:
            spot = found[0]
            return {"name": str(spot.get("name") or name), "country": str(spot.get("country") or ""), "latitude": float(spot["latitude"]), "longitude": float(spot["longitude"])}
    raise NoSuchCity(f"no such city: {city}")


def _for_reading(name: str, language: str) -> str:
    """A place's name for the cat's own lines. The service has Uzbek names in Latin
    letters and the cat's Uzbek is in Cyrillic ones, so such a name is respelled, if the
    rules of the two alphabets can do it ("Toshkent", but not "New York")."""
    if language == "uz" and not _cyrillic(name):
        made = translit.to_cyrillic(name)
        if not any(ch.isascii() and ch.isalpha() for ch in made):
            return made
    return name


def fetch(city: str, place: str = PLACE, forecast: str = FORECAST, timeout: float = 10.0, language: str = "en", shown: str = "", spot: dict | None = None) -> dict:
    """Ask the service: where the city is (unless `spot` holds that from last time), then
    its weather. `shown` is the city as the person typed it, which the cat's lines then
    use; for a guessed city they use the service's name for it. Raises NoSuchCity when
    the service knows no such place, OSError or ValueError when it cannot be reached or
    answers in another shape."""
    spot = spot or find(city, language, place, timeout)
    told = _get(forecast, {
        "latitude": spot["latitude"], "longitude": spot["longitude"], "current": "temperature_2m,weather_code",
        "hourly": "precipitation_probability,weather_code", "daily": "temperature_2m_max,temperature_2m_min", "timezone": "auto", "forecast_days": 2,
    }, timeout)
    hourly = told.get("hourly") or {}
    return {
        "asked": city.strip().lower(), "city": shown or _for_reading(spot["name"], language), "at": time.time(),
        "place": ", ".join(part for part in (spot["name"], spot.get("country")) if part),  # what the service found, in its own words
        "spot": spot,  # kept, so that the name is not sent again
        "temp": round(float(told["current"]["temperature_2m"])), "code": int(told["current"]["weather_code"]),
        "high": round(float(told["daily"]["temperature_2m_max"][0])), "low": round(float(told["daily"]["temperature_2m_min"][0])),
        # the hours to come, each ("2026-11-13T15:00", chance of rain or snow in per cent, weather code)
        "hours": [list(hour) for hour in zip(hourly.get("time") or [], hourly.get("precipitation_probability") or [], hourly.get("weather_code") or [])],
    }


def coming(data: dict, now: dt.datetime, within: float = 8.0, chance: int = 55):
    """("rain" | "snow", "15:00") for the first hour within `within` hours from now in which
    rain or snow is likely; None if there is none, or if it is falling already."""
    if int(data.get("code", 0)) in RAIN | SNOW:
        return None
    for stamp, likely, code in data.get("hours") or []:
        try:
            at = dt.datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if now <= at <= now + dt.timedelta(hours=within) and (likely or 0) >= chance and int(code) in RAIN | SNOW:
            return ("snow" if int(code) in SNOW else "rain"), at.strftime("%H:%M")
    return None


def line(data: dict, now: dt.datetime) -> str:
    """The weather as the cat says it."""
    sky = T(SKY.get(int(data["code"]), N_("cloudy")))
    parts = [T("{city}: {temp} °C, {sky}. Today between {low} and {high} °C.", city=data["city"], temp=data["temp"], sky=sky, low=data["low"], high=data["high"])]
    ahead = coming(data, now)
    if ahead and ahead[0] == "rain":
        parts.append(T("Rain is likely around {time}: an umbrella would be wise.", time=ahead[1]))
    elif ahead:
        parts.append(T("Snow is likely around {time}. I will stay inside, thank you.", time=ahead[1]))
    elif data["high"] >= 35:
        parts.append(T("It gets hot: drink water. I will guard the coolest spot."))
    elif data["low"] <= -5:
        parts.append(T("Dress warmly: I have fur, you do not."))
    return " ".join(parts)


class Weather:
    """Keeps the forecast for the person's city fresh, quietly, while that is switched on."""

    def __init__(self, app):
        self.app = app
        kept = app.store.get("weather")
        self.data = kept if isinstance(kept, dict) and "hours" in kept else None
        self.fetching = False
        self.next_try = 0.0
        self.unknown = ""  # a city the service did not know: not asked for again until another one is typed
        self.seen_city = None  # the city as of the last look, to notice that another one was typed

    def city(self) -> str:
        return (self.app.settings["weather_city"] or guess_city()).strip()

    def fresh(self, now: float):
        """The forecast, if there is one for the city as it is set now and it is not old."""
        data = self.data
        if not self.app.settings["weather"] or data is None or data.get("asked") != self.city().lower() or now - data.get("at", 0) > 2 * KEEP:
            return None
        return data

    def tick(self, now: float) -> None:
        """Called every half minute: ask the service when there is nothing fresh."""
        settings = self.app.settings
        city = self.city()
        if city.lower() != self.seen_city:  # another city was typed: start afresh, and say its weather once it is here
            if self.seen_city is not None:
                self.app.said.discard("weather")
            self.seen_city, self.next_try, self.unknown = city.lower(), 0.0, ""
        if not settings["weather"] or not settings["first_run_done"] or not city or self.fetching or now < self.next_try or city.lower() == self.unknown:
            return
        if self.app.last_idle >= AWAY:
            return
        if self.data is not None and self.data.get("asked") == city.lower() and now - self.data.get("at", 0) < KEEP:
            return
        self.fetching = True
        typed = " ".join(settings["weather_city"].split())
        language = i18n.current
        spot = self.data.get("spot") if self.data is not None and self.data.get("asked") == city.lower() else None

        def work() -> None:
            try:
                found = fetch(city, language=language, shown=typed, spot=spot)
            except NoSuchCity:
                log.info("the weather service knows no city called %s", city)
                found = {"unknown": city}
            except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                log.info("no weather for %s: %s", city, error)
                found = None
            self.app.inbox.put(("weather", found))

        threading.Thread(target=work, name="weather", daemon=True).start()

    def arrived(self, found) -> None:
        """(On the window's thread.) The service answered, or did not."""
        self.fetching = False
        if found is None:
            self.next_try = time.time() + RETRY
            return
        if "unknown" in found:
            self.unknown = found["unknown"].lower()
            if " ".join(self.app.settings["weather_city"].split()).lower() == self.unknown:  # typed by the person, and still what stands there
                self.app.city_unknown(found["unknown"])
            return
        self.data = found
        self.app.store.put("weather", found)
