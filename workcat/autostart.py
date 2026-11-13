"""'Start with Windows': one value under the current user's Run key, nothing else.

The value carries the app's name, which is what Windows shows in its list of programs
that start with it. A value left by a version that had the app's earlier name counts as
"on" too, and is replaced by one with the present name the first time this is written.
"""
from __future__ import annotations

import os
import sys
import winreg
from pathlib import Path

from . import APP_NAME, OLD_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = APP_NAME
OLD_VALUE = OLD_NAME


def command() -> str:
    """How to start this copy of the app without a console window."""
    packed = os.environ.get("WORKCAT_EXE")  # set by the installed program's own .exe (the variable kept its name)
    if packed and Path(packed).is_file():
        return f'"{packed}"'
    if getattr(sys, "frozen", False):  # packed into an .exe some other way
        return f'"{sys.executable}"'
    launcher = Path(__file__).resolve().parent.parent / f"{APP_NAME}.pyw"
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    return f'"{windowed if windowed.exists() else python}" "{launcher}"'


def _has(value: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, value)
            return True
    except OSError:
        return False


def enabled() -> bool:
    return _has(VALUE) or _has(OLD_VALUE)


def set_enabled(on: bool) -> bool:
    """Returns True if the change was made."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
            for value in (OLD_VALUE,) if on else (VALUE, OLD_VALUE):
                try:
                    winreg.DeleteValue(key, value)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def adopt_old_value() -> bool:
    """An entry under the app's earlier name starts a program that may be gone by now:
    it is written anew under the present name, pointing at this copy. True if it was."""
    return _has(OLD_VALUE) and set_enabled(True)
