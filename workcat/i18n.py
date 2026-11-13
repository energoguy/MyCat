"""Words. Every sentence the person sees goes through T(), with the English text as the key.

A language is one file, lang/<code>.json, mapping each English sentence to its
translation. A sentence without a translation simply stays English, and a translation
whose {placeholders} are broken falls back to English instead of failing.

    T("Break: {n} min left.", n=3)     translate now, for the screen
    N_("Proud")                        mark a word that is stored in a table and translated
                                       later, where it is shown: T(MOOD_WORDS[mood])

tools/strings.py finds every T() and N_() text in the code and checks the language files
against them.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

# code -> the language's own name, as shown in the language list
LANGUAGES = {"en": "English", "ru": "Русский", "uz": "Ўзбекча"}

_table: dict = {}
_plain = 0
current = "en"


def N_(message: str) -> str:
    """Marks a text for translation without translating it yet."""
    return message


def load(language: str) -> None:
    global _table, current
    _table = {}
    current = language if language in LANGUAGES else "en"
    if current == "en":
        return
    try:
        table = json.loads((Path(__file__).parent / "lang" / f"{current}.json").read_text(encoding="utf-8"))
        _table = {key: value for key, value in table.items() if isinstance(value, str) and value}
    except (OSError, ValueError, AttributeError):
        _table = {}


def T(message: str, /, **values) -> str:
    text = message if _plain else _table.get(message, message)
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):  # a translation with a broken placeholder
        return message.format(**values)


@contextmanager
def plain():
    """English inside this block, whatever language is set: for text that is handed to
    the AI model as facts, not shown on the screen."""
    global _plain
    _plain += 1
    try:
        yield
    finally:
        _plain -= 1


def system_language() -> str:
    """The language Windows itself is shown in, if it is one we have; else English."""
    try:
        import ctypes

        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError, ImportError):
        return "en"
    return {0x19: "ru", 0x43: "uz"}.get(primary, "en")


def duration(seconds: float) -> str:
    """'3 h 05 min', '42 min' or 'under a minute'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return T("under a minute")
    if minutes < 60:
        return T("{m} min", m=minutes)
    return T("{h} h {m:02d} min", h=minutes // 60, m=minutes % 60)
