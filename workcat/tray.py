"""The icon in the notification area and the shortcut keys that work in any program.

Tk cannot do either, so a small hidden Win32 window does, on its own thread with its own
message loop. It only reports what happened into a queue; the app reads the queue on the
Tk thread and decides what to do.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import struct
import threading
from ctypes import wintypes as wt
from pathlib import Path

from . import INSTANCE, hotkeys, sprites

log = logging.getLogger("workcat")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_DESTROY, WM_CLOSE, WM_HOTKEY = 0x0002, 0x0010, 0x0312
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_TRAY = 0x8000 + 1
WM_KEYS = 0x8000 + 2  # our own note to this thread: register the shortcut keys again
WINDOW_CLASS = "WorkCatTray"
# Two things another program may ask of a running cat (the app started a second time; the
# setup program before it replaces the files). Windows gives each name a number of its own.
ASK_SHOW, ASK_QUIT = "WorkCatShow", "WorkCatQuit"
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON = 49
MOD_NOREPEAT = 0x4000


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HANDLE),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HANDLE),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HANDLE),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wt.HANDLE),
    ]


def _fn(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = argtypes
    return f


_DefWindowProcW = _fn(user32, "DefWindowProcW", LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_RegisterClassW = _fn(user32, "RegisterClassW", wt.ATOM, ctypes.POINTER(WNDCLASSW))
_CreateWindowExW = _fn(user32, "CreateWindowExW", wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HANDLE, wt.HINSTANCE, ctypes.c_void_p)
_DestroyWindow = _fn(user32, "DestroyWindow", wt.BOOL, wt.HWND)
_GetMessageW = _fn(user32, "GetMessageW", ctypes.c_int, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
_TranslateMessage = _fn(user32, "TranslateMessage", wt.BOOL, ctypes.POINTER(wt.MSG))
_DispatchMessageW = _fn(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wt.MSG))
_PostMessageW = _fn(user32, "PostMessageW", wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_PostQuitMessage = _fn(user32, "PostQuitMessage", None, ctypes.c_int)
_RegisterWindowMessageW = _fn(user32, "RegisterWindowMessageW", wt.UINT, wt.LPCWSTR)
_RegisterHotKey = _fn(user32, "RegisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int, wt.UINT, wt.UINT)
_UnregisterHotKey = _fn(user32, "UnregisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int)
_FindWindowW = _fn(user32, "FindWindowW", wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
_GetWindowThreadProcessId = _fn(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
_AllowSetForegroundWindow = _fn(user32, "AllowSetForegroundWindow", wt.BOOL, wt.DWORD)
_LoadImageW = _fn(user32, "LoadImageW", wt.HANDLE, wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT)
_GetSystemMetrics = _fn(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
_GetModuleHandleW = _fn(kernel32, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR)
_Shell_NotifyIconW = _fn(shell32, "Shell_NotifyIconW", wt.BOOL, wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW))


def write_icon(path: Path, coat: str = "grey", sizes: tuple = (16, 32, 48)) -> Path:
    """Save the cat's face as a .ico (16, 32 and 48 px unless told otherwise; any multiple
    of 16 up to 256), straight from the sprite data."""
    pal = sprites.palette(coat)
    images = []
    for size in sizes:
        rows = sprites.icon_rows(size)
        pixels = bytearray()
        mask = bytearray()
        stride = ((size + 31) // 32) * 4
        for row in reversed(rows):  # bitmaps are stored bottom row first
            bits = bytearray(stride)
            for x, ch in enumerate(row):
                if ch == sprites.EMPTY:
                    pixels += b"\0\0\0\0"
                    bits[x // 8] |= 0x80 >> (x % 8)
                else:
                    colour = pal[ch]
                    pixels += bytes((int(colour[5:7], 16), int(colour[3:5], 16), int(colour[1:3], 16), 255))
            mask += bits
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
        images.append((size, header + bytes(pixels) + bytes(mask)))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, data in images:
        out += struct.pack("<BBBBHHII", size & 255, size & 255, 0, 0, 1, 32, len(data), offset)  # 256 is written as 0
        offset += len(data)
    path.write_bytes(out + b"".join(data for _, data in images))
    return path


def free(keys: str) -> bool:
    """True if no program holds this shortcut right now (ours included)."""
    parsed = hotkeys.parse(keys)
    if not parsed:
        return False
    probe = 0xBF00  # a number of our own for the moment it takes
    if not _RegisterHotKey(None, probe, parsed[0] | MOD_NOREPEAT, parsed[1]):
        return False
    _UnregisterHotKey(None, probe)
    return True


def call_running(name: str) -> bool:
    """Ask the cat that is already running under this name to show itself. False if
    there is none to ask (an older version, which does not listen, still gets the note)."""
    hwnd = _FindWindowW(WINDOW_CLASS, name)
    if not hwnd:
        return False
    owner = wt.DWORD(0)
    _GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value:
        _AllowSetForegroundWindow(owner.value)  # we were just started by the person: it may come to the front
    return bool(_PostMessageW(hwnd, _RegisterWindowMessageW(ASK_SHOW), 0, 0))


class Tray(threading.Thread):
    """Puts 'click', 'menu', 'key:<name>' (a shortcut key was pressed), 'keys' (the
    shortcuts were registered), 'show' or 'quit' (asked by another program, see ASK_SHOW)
    into `events` as they happen.

    `shortcuts` is {name: "Ctrl+Alt+H"}; see hotkeys.py. Windows ties a shortcut to the
    thread that registered it, so set_shortcuts() only leaves a note for this thread.
    `name` is what other programs find this cat by: one name for each data folder."""

    def __init__(self, icon_path: Path, tip: str, shortcuts=None, name: str = INSTANCE):
        super().__init__(name="tray", daemon=True)
        self.icon_path = str(icon_path)
        self.tip = tip
        self.window_name = name
        self._asked: dict = {}  # the number of a message another program may send -> what it means
        self.events: queue.Queue = queue.Queue()
        self.hwnd = None
        self.ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # must outlive the window
        self._taskbar_created = 0
        self._icon = None
        self.added = False  # the icon is in the notification area
        self._lock = threading.Lock()
        self._wanted = dict(shortcuts or {})
        self._ids: dict = {}  # the number Windows knows a shortcut by -> its name
        self.taken: set = set()  # names whose key another program already holds

    def set_shortcuts(self, shortcuts: dict) -> None:
        """Use these shortcut keys from now on. Safe to call from any thread."""
        with self._lock:
            self._wanted = dict(shortcuts)
        if self.hwnd:
            _PostMessageW(self.hwnd, WM_KEYS, 0, 0)

    def _register(self) -> None:
        for number in self._ids:
            _UnregisterHotKey(self.hwnd, number)
        with self._lock:
            wanted = dict(self._wanted)
        ids, taken = {}, set()
        for number, (name, keys) in enumerate(sorted(wanted.items()), start=1):
            parsed = hotkeys.parse(keys)
            if not parsed:
                continue
            if _RegisterHotKey(self.hwnd, number, parsed[0] | MOD_NOREPEAT, parsed[1]):
                ids[number] = name
            else:
                taken.add(name)
                log.info("%s is taken by another program", keys)
        self._ids, self.taken = ids, taken

    def run(self) -> None:
        try:
            instance = _GetModuleHandleW(None)
            cls = WNDCLASSW()
            cls.lpfnWndProc = self._proc
            cls.hInstance = instance
            cls.lpszClassName = WINDOW_CLASS
            _RegisterClassW(ctypes.byref(cls))
            asked = ((_RegisterWindowMessageW(ASK_SHOW), "show"), (_RegisterWindowMessageW(ASK_QUIT), "quit"))
            self._asked = {number: what for number, what in asked if number}
            self.hwnd = _CreateWindowExW(0, WINDOW_CLASS, self.window_name, 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._taskbar_created = _RegisterWindowMessageW("TaskbarCreated")
            size = _GetSystemMetrics(SM_CXSMICON) or 16
            self._icon = _LoadImageW(None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            self._notify(NIM_ADD)
            self._register()
            self.events.put("keys")
        except Exception:
            log.exception("tray start")
            self.ready.set()
            return
        self.ready.set()
        msg = wt.MSG()
        while _GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _TranslateMessage(ctypes.byref(msg))
            _DispatchMessageW(ctypes.byref(msg))

    def _notify(self, action: int) -> None:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon
        data.szTip = self.tip[:127]
        ok = bool(_Shell_NotifyIconW(action, ctypes.byref(data)))
        if action == NIM_ADD:
            self.added = ok
            if not ok:
                log.info("the tray icon could not be added")

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    self.events.put("click")
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.events.put("menu")
                return 0
            if msg == WM_HOTKEY:
                name = self._ids.get(int(wparam))
                if name:
                    self.events.put("key:" + name)
                return 0
            if msg == WM_KEYS:
                self._register()
                self.events.put("keys")
                return 0
            if msg in self._asked:
                self.events.put(self._asked[msg])
                return 0
            if msg == self._taskbar_created and msg:
                self._notify(NIM_ADD)  # Explorer restarted and forgot every icon
                return 0
            if msg == WM_CLOSE:
                for number in self._ids:
                    _UnregisterHotKey(hwnd, number)
                self._notify(NIM_DELETE)
                _DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                _PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("tray message")
        return _DefWindowProcW(hwnd, msg, wparam, lparam)

    def stop(self) -> None:
        if self.hwnd:
            _PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.join(1.5)
