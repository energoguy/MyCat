"""A packed copy checks itself:  MyCat.exe --check report.json

The installer carries its own Python. This starts the real app for a few seconds on a
throwaway data folder, opens its windows once, and writes down what was loaded and from
where. Everything must come from the program's own folder or from Windows: a module or a
DLL borrowed from some other Python on this computer would be missing on the next
person's.
"""
from __future__ import annotations

import ctypes
import importlib
import json
import logging
import os
import pkgutil
import shutil
import sys
import tempfile
import traceback
from ctypes import wintypes as wt
from pathlib import Path

# What the app and its tools import from Python itself.
NEEDED = (
    "tkinter", "tkinter.ttk", "tkinter.font", "tkinter.messagebox", "sqlite3", "ssl", "ctypes", "json", "urllib.request",
    "zipfile", "hashlib", "wave", "winsound", "winreg", "bz2", "lzma", "zlib", "unicodedata", "logging.handlers",
    "webbrowser", "argparse", "queue", "threading", "subprocess", "base64", "struct", "math", "random", "datetime",
)
# DLLs the program brings along: one of these coming from anywhere else means it leans on this computer.
OURS = ("python3", "vcruntime140", "tcl86", "tk86", "sqlite3", "libcrypto", "libssl", "libffi", "zlib1")


def loaded_dlls() -> list:
    """The path of every DLL in this process."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.POINTER(wt.HMODULE), wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
    process = kernel32.GetCurrentProcess()
    handles = (wt.HMODULE * 4096)()
    needed = wt.DWORD()
    if not psapi.EnumProcessModulesEx(process, handles, ctypes.sizeof(handles), ctypes.byref(needed), 3):
        return []
    found = []
    name = ctypes.create_unicode_buffer(1024)
    for handle in handles[: needed.value // ctypes.sizeof(wt.HMODULE)]:
        if psapi.GetModuleFileNameExW(process, handle, name, 1024):
            found.append(name.value)
    return found


def _try_the_app(facts: dict, problems: list) -> None:
    """The real app on an empty data folder: every window once, then quit."""
    from .app import App

    folder = Path(tempfile.mkdtemp(prefix="workcat-check-"))

    class Catch(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                text = record.getMessage()
                if record.exc_info:
                    text += "\n" + "".join(traceback.format_exception(*record.exc_info))
                problems.append(text)

    logging.getLogger("workcat").addHandler(Catch())
    app = App(folder, overrides={"first_run_done": True, "language": "en", "hide_from_capture": False})
    app.root.report_callback_exception = lambda kind, value, tb: problems.append("".join(traceback.format_exception(kind, value, tb)))

    def windows() -> None:
        from tkinter import font as tkfont

        facts["tk"] = str(app.root.tk.call("info", "patchlevel"))
        facts["tcl library"] = str(app.root.tk.eval("info library"))
        facts["font"] = "Segoe UI" in tkfont.families(app.root)
        for tab in ("today", "chat", "tasks", "habits", "apps", "brain", "settings"):
            app.open_panel(tab)
            app.root.update()
        app.panel.hide()
        x0, y0, x1, _y1 = app.pet.box()
        app.show_menu((x0 + x1) // 2, y0)
        app.root.update()
        app.menu.close()
        app.voice.say("Hello from the self-check.", kind="reply", ttl=2)
        facts["windows"] = "all opened"

    def look() -> None:
        try:
            windows()
        finally:
            app.root.after(1500, app.quit)  # only once the windows are done: a first start is slow

    app.root.after(1200, look)
    app.run()
    facts["tray icon"] = bool(app.tray.added)
    shutil.rmtree(folder, ignore_errors=True)


def run(report: Path) -> int:
    """Check this copy and write what was found to `report`. 0 if all is well."""
    problems: list = []
    packed = os.environ.get("WORKCAT_EXE", "")
    home = Path(packed).resolve().parent if packed else Path(__file__).resolve().parent.parent
    facts: dict = {"packed": bool(packed), "home": str(home), "executable": sys.executable, "prefix": sys.prefix, "python": sys.version.split()[0]}
    try:
        from . import __version__

        facts["version"] = __version__
        for name in NEEDED:
            try:
                importlib.import_module(name)
            except Exception as error:  # noqa: BLE001 - any failure is the finding
                problems.append(f"cannot import {name}: {error!r}")
        package = importlib.import_module("workcat")
        for module in pkgutil.iter_modules(package.__path__):
            if module.name != "__main__":
                importlib.import_module("workcat." + module.name)
        import sqlite3
        import ssl

        facts["sqlite"] = sqlite3.sqlite_version
        facts["openssl"] = ssl.OPENSSL_VERSION
        ssl.create_default_context()  # the certificates Windows keeps can be read
        _try_the_app(facts, problems)
    except Exception:  # noqa: BLE001
        problems.append(traceback.format_exc())

    inside = os.path.normcase(str(home)) + os.sep
    windows = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")) + os.sep
    modules = sorted({os.path.normcase(os.path.abspath(m.__file__)) for m in list(sys.modules.values()) if getattr(m, "__file__", None)})
    dlls = sorted({os.path.normcase(path) for path in loaded_dlls()})
    facts["modules"] = len(modules)
    facts["dlls"] = len(dlls)
    # "_clr" marks Windows' own copies for .NET: those are part of Windows, not of us
    ours = [path for path in dlls if os.path.basename(path).startswith(OURS) and "_clr" not in os.path.basename(path)]
    facts["our dlls from"] = sorted({os.path.dirname(path) for path in ours})
    if packed:
        strays = [path for path in modules if not path.startswith(inside)]
        strays += [path for path in ours if not path.startswith(inside)]
        strays += [path for path in dlls if "python" in path and not path.startswith((inside, windows))]
        for path in sorted(set(strays)):
            problems.append("loaded from outside the program's folder: " + path)
    facts["problems"] = problems
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return 2
    return 1 if problems else 0
