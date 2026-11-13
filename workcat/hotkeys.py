"""Shortcut keys, as people read them ("Ctrl+Alt+Space") and as Windows wants them.

Pure functions: nothing here touches the keyboard. tray.py registers the keys with
Windows; the Settings window lets you press a new combination.
"""
from __future__ import annotations

from .i18n import N_

# What can have a shortcut, the key it starts with, and what Settings calls it.
DEFAULTS = {"toggle": "Ctrl+Alt+H", "ask": "Ctrl+Alt+Space", "focus": "Ctrl+Alt+F", "task": "Ctrl+Alt+T"}
NAMES = {
    "toggle": N_("Show or hide me"),
    "ask": N_("Ask me something"),
    "focus": N_("Start or stop a focus round"),
    "task": N_("Add a task"),
}
# Another program may already hold a usual key (some assistants take Ctrl+Alt+Space, for
# one). Then the first of these that is free is used instead, and Settings shows it.
SPARES = {
    "toggle": ("Ctrl+Alt+Shift+H", "Ctrl+Alt+J"),
    "ask": ("Ctrl+Alt+A", "Ctrl+Alt+Shift+Space", "Ctrl+Alt+Q"),
    "focus": ("Ctrl+Alt+Shift+F", "Ctrl+Alt+G"),
    "task": ("Ctrl+Alt+Shift+T", "Ctrl+Alt+Y"),
}

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
_MODS = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN))  # in the order they are written

_KEYS = {chr(code): code for code in range(ord("A"), ord("Z") + 1)}
_KEYS.update({str(digit): 0x30 + digit for digit in range(10)})
_KEYS.update({f"F{n}": 0x6F + n for n in range(1, 13)})
_KEYS.update({"Space": 0x20, "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Insert": 0x2D, "Delete": 0x2E})
_BY_CODE = {code: name for name, code in _KEYS.items()}
_SPELLED = {name.lower(): name for name in _KEYS}
_SPELLED.update({"control": "Ctrl", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "windows": "Win"})


def parse(text: str):
    """(modifiers, key code) for 'Ctrl+Alt+H', or None if that is not a usable shortcut.

    Usable means one ordinary key together with Ctrl, Alt or the Windows key. Shift alone
    is not enough, and neither is a bare key: either would take a letter away from typing."""
    mods, key = 0, None
    for part in str(text or "").replace(" ", "").split("+"):
        name = _SPELLED.get(part.lower())
        if name is None:
            return None
        flag = dict(_MODS).get(name)
        if flag:
            mods |= flag
        elif key is None:
            key = _KEYS[name]
        else:
            return None  # two keys
    if key is None or not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None
    return mods, key


def spell(mods: int, key: int) -> str:
    """'Ctrl+Alt+H' for what parse() returned. '' if the key has no name here."""
    if key not in _BY_CODE:
        return ""
    return "+".join([name for name, flag in _MODS if mods & flag] + [_BY_CODE[key]])


def tidy(text: str) -> str:
    """A shortcut in its one true spelling, or '' if it is not usable."""
    parsed = parse(text)
    return spell(*parsed) if parsed else ""


def pressed(state: int, keycode: int) -> str:
    """The shortcut for a key press in a Tk window: `state` and `keycode` of the event.
    '' while only Ctrl, Alt or Shift are down, or if the combination is not usable.
    The key's code is used, not its letter, so it works in any keyboard layout."""
    mods = (MOD_CONTROL if state & 0x0004 else 0) | (MOD_ALT if state & 0x20000 else 0) | (MOD_SHIFT if state & 0x0001 else 0)
    return tidy(spell(mods, keycode))


def merged(saved) -> dict:
    """The shortcuts to use: the saved ones where they are usable, the usual ones
    otherwise. '' means: no shortcut for this."""
    out = dict(DEFAULTS)
    if isinstance(saved, dict):
        for name in DEFAULTS:
            if name in saved:
                out[name] = tidy(saved[name]) if saved[name] else ""
    return out


def spare(name: str, shortcuts: dict, free) -> str:
    """Keys to use for `name` when another program holds its usual ones: the first spare
    that none of our own shortcuts uses and that `free(keys)` says nobody else holds.
    '' if there is none."""
    ours = set(shortcuts.values())
    for keys in SPARES.get(name, ()):
        if keys not in ours and free(keys):
            return keys
    return ""


def clashes(shortcuts: dict) -> set:
    """The names that share a shortcut with another name."""
    seen: dict = {}
    for name, keys in shortcuts.items():
        if keys:
            seen.setdefault(keys, []).append(name)
    return {name for names in seen.values() if len(names) > 1 for name in names}
