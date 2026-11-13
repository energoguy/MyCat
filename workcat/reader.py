"""Reading what another program shows in its window, as text.

Only ever done for a program the person ticked in the AI brain tab, with the switch
"Read what other programs show" on, and only at the moment they ask (or one of their
daily scripts does). Nothing here clicks, scrolls or types into the other program: it is
read the way a screen reader reads it, through the interface Windows offers for that
(UI Automation). What comes back is the text the window shows right now.

    read(hwnd)            -> Reading (text, how it was read, how long it took)
    showing()             -> the programs that have a window up now
    window_of(program)    -> that program's window, or 0

Fields marked as passwords are skipped. The text is handed to whoever asked and kept
nowhere here.

How: Windows' automation object is asked for every element of the window in one go,
with the few facts needed about each (its name, kind and value, whether it is a password
field, whether it is scrolled out of view). A page or document that offers its text as a
whole (browsers, Word, Notepad) is asked for the part that is in view instead. All of it
happens on a thread of its own with a time limit: a program that does not answer must
not stop the cat.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from collections import deque
from ctypes import wintypes as wt
from dataclasses import dataclass

from . import apps, win32

log = logging.getLogger("workcat")

MOST = 6000  # characters of a window's text that are handed on, at most
SECONDS = 6.0  # how long a window gets to answer
PIECE = 1500  # ... and of one element's text

HRESULT = ctypes.c_long
COINIT_MULTITHREADED = 0
CLSCTX_INPROC_SERVER = 1
VT_I4, VT_BSTR, VT_BOOL = 3, 8, 11
TREE_DESCENDANTS = 4
MODE_NONE = 0  # elements as plain records of what was asked for, with no line back to the program

# What is asked about every element.
NAME, KIND, PASSWORD, OFFSCREEN, VALUE = 30005, 30003, 30019, 30022, 30045
TEXT_PATTERN = 10014
# Kinds of element whose words are what a window "shows" (and not its buttons and menus).
EDIT, LINK, LIST_ITEM, TREE_ITEM, TEXT, DATA_ITEM, DOCUMENT, HEADER_ITEM, GROUP, TAB_ITEM = 50004, 50005, 50007, 50024, 50020, 50029, 50030, 50035, 50026, 50019
WORDS = frozenset((EDIT, LINK, LIST_ITEM, TREE_ITEM, TEXT, DATA_ITEM, DOCUMENT, HEADER_ITEM))
VALUED = frozenset((EDIT, DATA_ITEM, DOCUMENT))  # here the value is what is written in it, and the name only its label


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


class VARIANT(ctypes.Structure):
    class _Value(ctypes.Union):
        _fields_ = [("number", ctypes.c_long), ("flag", ctypes.c_short), ("pointer", ctypes.c_void_p), ("wide", ctypes.c_longlong)]

    _fields_ = [("kind", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort), ("value", _Value), ("more", ctypes.c_void_p)]


_ole32 = ctypes.WinDLL("ole32")
_oleaut32 = ctypes.WinDLL("oleaut32")
_ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_ole32.CoInitializeEx.restype = HRESULT
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = HRESULT
_oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
_oleaut32.SysStringLen.restype = ctypes.c_uint
_oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
_oleaut32.VariantClear.argtypes = [ctypes.POINTER(VARIANT)]


def _guid(text: str) -> GUID:
    made = GUID()
    _ole32.CLSIDFromString(text, ctypes.byref(made))
    return made


CLSID_AUTOMATION = _guid("{FF48DBA4-60EF-4201-AA87-54103EEF594E}")
IID_AUTOMATION = _guid("{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}")
IID_TEXT_PATTERN = _guid("{32EBA289-3583-42C9-9C59-3B6D9A1E9B6A}")

_PROTOTYPES: dict = {}
_POINTER = ctypes.sizeof(ctypes.c_void_p)
_RELEASE = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
OUT = ctypes.POINTER(ctypes.c_void_p)
_mine = threading.local()  # .held: every object the reading on this thread still holds


class Thing:
    """One object of Windows' (a COM object), held by its address and let go of when no
    longer needed. Its abilities are called by their place in its table, which is how
    they are listed in Windows' own description of it (UIAutomationClient.h)."""

    __slots__ = ("at",)

    def __init__(self, at: int):
        self.at = at
        held = getattr(_mine, "held", None)
        if held is not None:
            held.append(self)

    def call(self, place: int, kinds: tuple = (), *values) -> int:
        """Call ability number `place`. Returns Windows' verdict: below zero is a failure."""
        table = ctypes.c_void_p.from_address(self.at).value
        address = ctypes.c_void_p.from_address(table + place * _POINTER).value
        prototype = _PROTOTYPES.get(kinds)
        if prototype is None:
            prototype = _PROTOTYPES[kinds] = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *kinds)
        return prototype(address)(self.at, *values)

    def get(self, place: int, kinds: tuple = (), *values):
        """Call an ability that hands back another object; None if it did not."""
        found = ctypes.c_void_p()
        verdict = self.call(place, kinds + (OUT,), *values, ctypes.byref(found))
        return Thing(found.value) if verdict >= 0 and found.value else None

    def number(self, place: int) -> int:
        found = ctypes.c_int()
        return found.value if self.call(place, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(found)) >= 0 else 0

    def fact(self, place: int, which: int):
        """One fact about an element (abilities 10 and 12 of an element): text, number or yes/no."""
        value = VARIANT()
        if self.call(place, (ctypes.c_int, ctypes.POINTER(VARIANT)), which, ctypes.byref(value)) < 0:
            return None
        try:
            if value.kind == VT_BSTR:
                return _words(value.value.pointer, free=False)
            if value.kind == VT_I4:
                return value.value.number
            if value.kind == VT_BOOL:
                return value.value.flag != 0
            return None
        finally:
            _oleaut32.VariantClear(ctypes.byref(value))

    def close(self) -> None:
        """Let go of it. (Once: Windows counts, and frees the object at nought.)"""
        at, self.at = self.at, 0
        if at:
            table = ctypes.c_void_p.from_address(at).value
            _RELEASE(ctypes.c_void_p.from_address(table + 2 * _POINTER).value)(at)


def _words(pointer, free: bool = True) -> str:
    """The text of a string of Windows' (a BSTR)."""
    if not pointer:
        return ""
    try:
        return ctypes.wstring_at(pointer, _oleaut32.SysStringLen(pointer))
    finally:
        if free:
            _oleaut32.SysFreeString(pointer)


def _tidy(text: str) -> str:
    """One element's words on one line, without the signs programs put in for layout."""
    return " ".join(text.replace("​", "").replace("￼", " ").replace(" ", " ").split())


def _document(automation: Thing, window: Thing, most: int) -> str:
    """The part of a page or document that is in view, where the program offers its text
    as a whole (browsers, Word, Notepad). Empty where it does not."""
    kind = VARIANT()
    kind.kind, kind.value.number = VT_I4, DOCUMENT
    wanted = automation.get(23, (ctypes.c_int, VARIANT), KIND, kind)  # CreatePropertyCondition
    if wanted is None:
        return ""
    page = window.get(5, (ctypes.c_int, ctypes.c_void_p), TREE_DESCENDANTS, wanted.at)  # FindFirst
    if page is None:
        return ""
    if page.fact(10, PASSWORD):  # GetCurrentPropertyValue
        return ""
    held = ctypes.c_void_p()
    if page.call(16, (ctypes.c_int, OUT), TEXT_PATTERN, ctypes.byref(held)) < 0 or not held.value:  # GetCurrentPattern
        return ""
    plain = Thing(held.value)
    pattern = ctypes.c_void_p()
    if plain.call(0, (ctypes.POINTER(GUID), OUT), ctypes.byref(IID_TEXT_PATTERN), ctypes.byref(pattern)) < 0 or not pattern.value:  # QueryInterface
        return ""
    text = Thing(pattern.value)
    parts: list = []
    ranges = text.get(6)  # GetVisibleRanges
    count = ranges.number(3) if ranges is not None else 0
    for index in range(min(count, 200)):
        one = ranges.get(4, (ctypes.c_int,), index)
        if one is None:
            continue
        found = ctypes.c_void_p()
        if one.call(12, (ctypes.c_int, OUT), most, ctypes.byref(found)) >= 0:  # GetText
            parts.append(_words(found.value))
        one.close()
        if sum(len(part) for part in parts) >= most:
            break
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _elements(automation: Thing, window: Thing, most: int) -> str:
    """The words of everything in the window that carries words and is in view."""
    request = automation.get(20)  # CreateCacheRequest
    if request is None:
        return ""
    for which in (NAME, KIND, PASSWORD, OFFSCREEN, VALUE):
        request.call(3, (ctypes.c_int,), which)  # AddProperty
    request.call(11, (ctypes.c_int,), MODE_NONE)  # put_AutomationElementMode
    usual = automation.get(18)  # get_ControlViewCondition: what a person would call the window's parts
    if usual is None:
        return ""
    found = window.get(8, (ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p), TREE_DESCENDANTS, usual.at, request.at)  # FindAllBuildCache
    if found is None:
        return ""
    lines: list = []
    recent: deque = deque(maxlen=8)
    size = 0
    for index in range(found.number(3)):  # get_Length
        item = found.get(4, (ctypes.c_int,), index)  # GetElement
        if item is None:
            continue
        kind = item.fact(12, KIND)  # GetCachedPropertyValue
        if kind not in WORDS or item.fact(12, PASSWORD) or item.fact(12, OFFSCREEN):
            item.close()
            continue
        name = _tidy(item.fact(12, NAME) or "")
        value = _tidy(item.fact(12, VALUE) or "") if kind in VALUED else ""
        item.close()
        said = (f"{name}: {value}" if name and name != value else value) if value else name
        said = said[:PIECE]
        if len(said) < 2:
            continue
        # A row of a list is announced whole and then piece by piece: once is enough.
        if any(said in earlier for earlier in recent):
            continue
        recent.append(said)
        lines.append(said)
        size += len(said) + 1
        if size >= most:
            break
    return "\n".join(lines)


def _read(hwnd: int, most: int, into: dict) -> None:
    """(On its own thread.) Fills `into` with "text", or leaves it as it is."""
    if _ole32.CoInitializeEx(None, COINIT_MULTITHREADED) < 0:
        return
    _mine.held = []
    try:
        held = ctypes.c_void_p()
        if _ole32.CoCreateInstance(ctypes.byref(CLSID_AUTOMATION), None, CLSCTX_INPROC_SERVER, ctypes.byref(IID_AUTOMATION), ctypes.byref(held)) < 0 or not held.value:
            return
        automation = Thing(held.value)
        window = automation.get(6, (ctypes.c_void_p,), hwnd)  # ElementFromHandle
        if window is None:
            return
        page = _document(automation, window, most)
        parts = _elements(automation, window, most)
        # A page read as a whole has its words in the order they stand in; the elements add
        # what is around it (the list of chats beside the open one, say). Where the page has
        # most of it anyway, it alone is taken.
        if len(page) >= 200 and len(page) >= len(parts) * 0.6:
            into["text"] = page[:most]
        else:
            into["text"] = (parts or page)[:most]
    finally:
        # Everything is let go of here, on the thread that got it, and before this thread
        # leaves Windows' object system: nothing is left for a later moment or another thread.
        for thing in reversed(_mine.held):
            thing.close()
        _mine.held = None
        _ole32.CoUninitialize()


@dataclass(frozen=True)
class Reading:
    program: str  # as the cat knows it: "telegram", "chrome"
    name: str  # as people call it: "Telegram", "Chrome"
    title: str  # the window's title
    text: str  # what the window shows, or "" where nothing could be read
    took: float  # seconds
    why: str = ""  # where there is no text: "gone", "hidden", "late" or "nothing"
    how: str = "text"  # "text": as a screen reader gets it; "picture": recognised in a picture of the window


def text_of(hwnd: int, most: int = MOST, seconds: float = SECONDS) -> tuple:
    """(text, why not) of one window, read through Windows' interface for screen readers."""
    into: dict = {}
    worker = threading.Thread(target=_guarded, args=(hwnd, most, into), daemon=True, name="reader")
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return "", "late"  # it goes on by itself and is not listened to any more
    text = into.get("text", "")
    return text, "" if text else "nothing"


def _guarded(hwnd: int, most: int, into: dict) -> None:
    try:
        _read(hwnd, most, into)
    except Exception:  # noqa: BLE001  (another program's answer must never bring the cat down)
        log.exception("reading a window failed")


def identity(hwnd: int) -> tuple:
    """(program, name) of the program a window belongs to."""
    _pid, path = win32.app_of_window(hwnd)
    stem = apps.base_stem(apps.stem_of(path))
    return stem, apps.pretty_name(stem, win32.file_description(path) if path else "")


def showing() -> list:
    """The programs that have a window up now, the one in front first: (program, name, hwnd)."""
    seen, found = set(), []
    for win in win32.windows(os.getpid()):
        if not win.perch:
            continue
        program, name = identity(win.hwnd)
        if program and program not in seen:
            seen.add(program)
            found.append((program, name, win.hwnd))
    return found


def window_of(program: str) -> int:
    """The window of a program that is up now (its frontmost one), or 0."""
    for stem, _name, hwnd in showing():
        if stem == program:
            return hwnd
    return 0


def read(hwnd: int, most: int = MOST, seconds: float = SECONDS) -> Reading:
    """What one window shows."""
    started = time.monotonic()
    if not hwnd or not win32.is_window(hwnd):
        return Reading("", "", "", "", 0.0, "gone")
    program, name = identity(hwnd)
    title = win32.window_title(hwnd)
    if not win32.is_shown(hwnd):
        return Reading(program, name, title, "", 0.0, "hidden")
    text, why = text_of(hwnd, most, seconds)
    if why == "nothing" and win32.class_name(hwnd).startswith("Chrome_"):
        # A browser (and a program built on one) only starts describing its page once
        # somebody asks: the first asking wakes it, the second gets the answer.
        for _ in range(2):
            time.sleep(0.8)
            text, why = text_of(hwnd, most, max(1.0, seconds - (time.monotonic() - started)))
            if text:
                break
    how = "text"
    if len(text) < FEW and why != "late":
        # The program gives (almost) nothing to a screen reader: Windows' own text
        # recognition reads a picture of the window instead, on this computer.
        seen = picture_text(hwnd, most, max(2.0, seconds))
        if len(seen) > len(text):
            text, why, how = seen, "", "picture"
    return Reading(program, name, title, text, time.monotonic() - started, why, how)


# ---------------------------------------------------------------------------------------
# Reading a picture of the window. The window is asked to draw itself (nothing else of the
# screen is in the picture), and Windows' text recognition (Windows.Media.Ocr, part of
# Windows 10 and 11) reads it: with the languages Windows has for that, and without the
# picture leaving this computer. It is then dropped.

FEW = 40  # fewer characters than this count as "nothing to read"
BGRA8 = 87
_combase = None


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG), ("planes", wt.WORD), ("bits", wt.WORD), ("compression", wt.DWORD),
        ("image", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("used", wt.DWORD), ("important", wt.DWORD),
    ]


def _shot(hwnd: int):
    """(width, height, the window's picture as BGRA bytes), drawn by the window itself; None if it will not."""
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    user32.GetWindowDC.restype = gdi32.CreateCompatibleDC.restype = gdi32.CreateCompatibleBitmap.restype = gdi32.SelectObject.restype = ctypes.c_void_p
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = min(rect.right - rect.left, 4000), min(rect.bottom - rect.top, 4000)
    if width < 40 or height < 40:
        return None
    window = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(window)
    bitmap = gdi32.CreateCompatibleBitmap(window, width, height)
    before = gdi32.SelectObject(memory, bitmap)
    drawn = user32.PrintWindow(hwnd, memory, 2)
    gdi32.SelectObject(memory, before)
    header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(hwnd, window)
    return (width, height, pixels) if drawn else None


def _factory(name: str, iid: str):
    """One of Windows' newer objects (a WinRT class's "statics"), by its name."""
    global _combase
    if _combase is None:
        _combase = ctypes.WinDLL("combase")
        _combase.WindowsCreateString.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, OUT]
        _combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
        _combase.WindowsGetStringRawBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        _combase.WindowsGetStringRawBuffer.restype = ctypes.c_void_p
        _combase.RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), OUT]
        _combase.RoGetActivationFactory.restype = HRESULT
    label = ctypes.c_void_p()
    _combase.WindowsCreateString(name, len(name), ctypes.byref(label))
    found = ctypes.c_void_p()
    wanted = _guid(iid)
    verdict = _combase.RoGetActivationFactory(label, ctypes.byref(wanted), ctypes.byref(found))
    _combase.WindowsDeleteString(label)
    return Thing(found.value) if verdict >= 0 and found.value else None


def _recognise(shot, most: int, into: dict) -> None:
    """(On its own thread.) The words in a picture, into `into["text"]`."""
    if _ole32.CoInitializeEx(None, COINIT_MULTITHREADED) < 0:
        return
    _mine.held = []
    try:
        width, height, pixels = shot
        buffers = _factory("Windows.Security.Cryptography.CryptographicBuffer", "{320B7E22-3CB0-4CDF-8663-1D28910065EB}")
        bitmaps = _factory("Windows.Graphics.Imaging.SoftwareBitmap", "{DF0385DB-672F-4A9D-806E-C2442F343E86}")
        engines = _factory("Windows.Media.Ocr.OcrEngine", "{5BFFA85A-3384-3540-9940-699120D428A8}")
        if buffers is None or bitmaps is None or engines is None:
            into["why"] = "no text recognition in this Windows"
            return
        buffer = buffers.get(9, (ctypes.c_uint, ctypes.c_void_p), len(pixels.raw), ctypes.cast(pixels, ctypes.c_void_p))  # CreateFromByteArray
        if buffer is None:
            return
        bitmap = bitmaps.get(9, (ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int), buffer.at, BGRA8, width, height)  # CreateCopyFromBuffer
        engine = engines.get(10)  # TryCreateFromUserProfileLanguages
        if bitmap is None or engine is None:
            into["why"] = "no language for text recognition"
            return
        task = engine.get(6, (ctypes.c_void_p,), bitmap.at)  # RecognizeAsync
        if task is None:
            return
        info = ctypes.c_void_p()
        status_of = _guid("{00000036-0000-0000-C000-000000000046}")  # IAsyncInfo
        if task.call(0, (ctypes.POINTER(GUID), OUT), ctypes.byref(status_of), ctypes.byref(info)) < 0 or not info.value:
            return
        waiting = Thing(info.value)
        for _ in range(400):
            if waiting.number(7) != 0:  # get_Status: 0 is "still at it"
                break
            time.sleep(0.025)
        if waiting.number(7) != 1:
            return
        result = task.get(8)  # GetResults
        if result is None:
            return
        words = ctypes.c_void_p()
        if result.call(8, (OUT,), ctypes.byref(words)) < 0 or not words.value:  # get_Text
            return
        size = ctypes.c_uint()
        raw = _combase.WindowsGetStringRawBuffer(words, ctypes.byref(size))
        into["text"] = ctypes.wstring_at(raw, size.value)[:most] if raw else ""
        _combase.WindowsDeleteString(words)
    finally:
        for thing in reversed(_mine.held):
            thing.close()
        _mine.held = None
        _ole32.CoUninitialize()


def picture_text(hwnd: int, most: int = MOST, seconds: float = SECONDS) -> str:
    """What Windows' text recognition reads in a picture of one window; "" if nothing."""
    into: dict = {}

    def work() -> None:
        try:
            shot = _shot(hwnd)
            if shot is not None:
                _recognise(shot, most, into)
        except Exception:  # noqa: BLE001
            log.exception("reading a picture of a window failed")

    worker = threading.Thread(target=work, daemon=True, name="reader-picture")
    worker.start()
    worker.join(seconds + 4)
    return "" if worker.is_alive() else " ".join(into.get("text", "").split())
