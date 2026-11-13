"""Thin ctypes wrappers over the Win32 calls the cat needs. Windows only.

Everything here speaks physical desktop pixels: the process is made per-monitor DPI aware
before the first window exists, so window frames, the cursor and our own windows all share
one coordinate space.

What is read about other programs: window frames, styles, class names and the path of the
exe. A window title is read in exactly one place (window_title) and only when the caller
asks for it.
"""
from __future__ import annotations

import ctypes
import os
import winreg
from ctypes import wintypes as wt
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
shell32 = ctypes.WinDLL("shell32")
version = ctypes.WinDLL("version")

LONG_PTR = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def _fn(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = argtypes
    return f


_GetCursorPos = _fn(user32, "GetCursorPos", wt.BOOL, ctypes.POINTER(wt.POINT))
_GetAsyncKeyState = _fn(user32, "GetAsyncKeyState", ctypes.c_short, ctypes.c_int)
_GetLastInputInfo = _fn(user32, "GetLastInputInfo", wt.BOOL, ctypes.POINTER(LASTINPUTINFO))
_GetTickCount = _fn(kernel32, "GetTickCount", wt.DWORD)
_EnumWindows = _fn(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
_EnumChildWindows = _fn(user32, "EnumChildWindows", wt.BOOL, wt.HWND, WNDENUMPROC, wt.LPARAM)
_IsWindow = _fn(user32, "IsWindow", wt.BOOL, wt.HWND)
_IsWindowVisible = _fn(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
_IsIconic = _fn(user32, "IsIconic", wt.BOOL, wt.HWND)
_GetWindowRect = _fn(user32, "GetWindowRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
_GetClassNameW = _fn(user32, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_GetWindowTextW = _fn(user32, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_GetForegroundWindow = _fn(user32, "GetForegroundWindow", wt.HWND)
_GetAncestor = _fn(user32, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
_GetWindow = _fn(user32, "GetWindow", wt.HWND, wt.HWND, wt.UINT)
_GetWindowThreadProcessId = _fn(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
_SetWindowPos = _fn(user32, "SetWindowPos", wt.BOOL, wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)
_ShowWindow = _fn(user32, "ShowWindow", wt.BOOL, wt.HWND, ctypes.c_int)
_SetForegroundWindow = _fn(user32, "SetForegroundWindow", wt.BOOL, wt.HWND)
_EnumDisplayMonitors = _fn(user32, "EnumDisplayMonitors", wt.BOOL, wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM)
_GetMonitorInfoW = _fn(user32, "GetMonitorInfoW", wt.BOOL, wt.HANDLE, ctypes.POINTER(MONITORINFO))
_DwmGetWindowAttribute = _fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD)
_OpenProcess = _fn(kernel32, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_QueryFullProcessImageNameW = _fn(kernel32, "QueryFullProcessImageNameW", wt.BOOL, wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
_CloseHandle = _fn(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
_CreateMutexW = _fn(kernel32, "CreateMutexW", wt.HANDLE, ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
_SHQueryUserNotificationState = _fn(shell32, "SHQueryUserNotificationState", ctypes.c_long, ctypes.POINTER(ctypes.c_int))
_GetFileVersionInfoSizeW = _fn(version, "GetFileVersionInfoSizeW", wt.DWORD, wt.LPCWSTR, ctypes.POINTER(wt.DWORD))
_GetFileVersionInfoW = _fn(version, "GetFileVersionInfoW", wt.BOOL, wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p)
_VerQueryValueW = _fn(version, "VerQueryValueW", wt.BOOL, ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT))

# SetWindowLongPtrW is a real export only on 64-bit Windows
_GetWindowLongPtr = _fn(user32, "GetWindowLongPtrW" if hasattr(user32, "GetWindowLongPtrW") else "GetWindowLongW", LONG_PTR, wt.HWND, ctypes.c_int)
_SetWindowLongPtr = _fn(user32, "SetWindowLongPtrW" if hasattr(user32, "SetWindowLongPtrW") else "SetWindowLongW", LONG_PTR, wt.HWND, ctypes.c_int, LONG_PTR)

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GA_ROOT = 2
GW_OWNER = 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
HWND_TOPMOST = wt.HWND(-1)
SW_HIDE, SW_SHOWNOACTIVATE, SW_RESTORE = 0, 4, 9
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ALREADY_EXISTS = 183

VK_LBUTTON, VK_RBUTTON, VK_ESCAPE, VK_MENU = 0x01, 0x02, 0x1B, 0x12

# Shell surfaces: never a seat and never "the window you work in".
SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow"})


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class Monitor:
    rect: Rect
    work: Rect  # without the taskbar
    primary: bool


@dataclass(frozen=True)
class Win:
    hwnd: int
    rect: Rect  # the visible frame
    pid: int
    cls: str
    perch: bool  # an ordinary app window the cat may sit on


def _rect(r: wt.RECT) -> Rect:
    return Rect(r.left, r.top, r.right, r.bottom)


# --------------------------------------------------------------------------- process

def set_dpi_awareness() -> None:
    """Per-monitor DPI awareness; must run before any window exists."""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def system_dpi() -> int:
    try:
        return int(user32.GetDpiForSystem()) or 96
    except (AttributeError, OSError):
        return 96


def set_app_id(app_id: str) -> None:
    """Our windows get their own taskbar group and icon instead of Python's."""
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except (AttributeError, OSError):
        pass


class _JOB_BASIC_LIMITS(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class _JOB_EXTENDED_LIMITS(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOB_BASIC_LIMITS),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_job = None


def end_with_us(process_handle: int) -> None:
    """Tie a child process to this one: when we end, however that happens, Windows ends
    the child too. Used for the AI engine, so it never stays behind on its own."""
    global _job
    if _job is None:
        create = _fn(kernel32, "CreateJobObjectW", wt.HANDLE, ctypes.c_void_p, wt.LPCWSTR)
        configure = _fn(kernel32, "SetInformationJobObject", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
        job = create(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _JOB_EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not configure(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):  # 9 = extended limit information
            raise ctypes.WinError(ctypes.get_last_error())
        _job = job  # kept open for our whole life; closing it is what ends the children
    assign = _fn(kernel32, "AssignProcessToJobObject", wt.BOOL, wt.HANDLE, wt.HANDLE)
    if not assign(_job, wt.HANDLE(process_handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def total_memory() -> int:
    """Installed memory in bytes (0 if Windows will not say)."""
    kilobytes = ctypes.c_ulonglong(0)
    try:
        if kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kilobytes)):
            return kilobytes.value * 1024
    except (AttributeError, OSError):
        pass
    return 0


_mutex = None


def single_instance(name: str) -> bool:
    """True if this is the only running copy. The mutex lives as long as the process."""
    global _mutex
    _mutex = _CreateMutexW(None, False, "Local\\" + name)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


# --------------------------------------------------------------------------- input

def cursor() -> tuple:
    p = wt.POINT()
    _GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def key_down(vk: int) -> bool:
    return bool(_GetAsyncKeyState(vk) & 0x8000)


def idle_seconds() -> float:
    """Seconds since the last key press or mouse move anywhere in the session."""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((_GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


# Why now is a bad moment to show anything; the same test Windows uses for its own toasts.
QUIET_NO, QUIET_AWAY, QUIET_FULLSCREEN, QUIET_PRESENTING = "", "away", "fullscreen", "presenting"


def quiet_state() -> str:
    state = ctypes.c_int(0)
    if _SHQueryUserNotificationState(ctypes.byref(state)) < 0:
        return QUIET_NO
    return {1: QUIET_AWAY, 2: QUIET_FULLSCREEN, 3: QUIET_FULLSCREEN, 4: QUIET_PRESENTING}.get(state.value, QUIET_NO)


def mic_in_use() -> bool:
    """Some program holds the microphone right now: most likely a call.

    Windows keeps a start/stop time per program for its privacy page; a stop of 0 means
    "still using it". Nothing is recorded or listened to.
    """
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def scan(key) -> bool:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
            except OSError:
                return False
            i += 1
            try:
                with winreg.OpenKey(key, name) as sub:
                    if name == "NonPackaged":
                        if scan(sub):
                            return True
                        continue
                    stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                    if stop == 0:
                        return True
            except OSError:
                continue

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            return scan(key)
    except OSError:
        return False


# --------------------------------------------------------------------------- monitors

def monitors() -> list:
    """Every monitor, the primary one first."""
    out: list = []

    def each(handle, _dc, _clip, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if _GetMonitorInfoW(handle, ctypes.byref(info)):
            out.append(Monitor(_rect(info.rcMonitor), _rect(info.rcWork), bool(info.dwFlags & 1)))
        return True

    _EnumDisplayMonitors(None, None, MONITORENUMPROC(each), 0)
    out.sort(key=lambda m: not m.primary)
    return out


# --------------------------------------------------------------------------- other windows

def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(_IsWindow(hwnd))


def is_shown(hwnd: int) -> bool:
    """Exists, visible and not minimised."""
    return is_window(hwnd) and bool(_IsWindowVisible(hwnd)) and not _IsIconic(hwnd)


def frame(hwnd: int):
    """The visible frame of a window, without the invisible resize borders. None if gone."""
    r = wt.RECT()
    if _DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        if not _GetWindowRect(hwnd, ctypes.byref(r)):
            return None
    return _rect(r)


def _cloaked(hwnd: int) -> bool:
    value = wt.DWORD(0)
    _DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    _GetClassNameW(hwnd, buf, 128)
    return buf.value


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _GetWindowTextW(hwnd, buf, 512)
    return buf.value


def pid_of(hwnd: int) -> int:
    pid = wt.DWORD(0)
    _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _describe(hwnd: int, own_pid: int):
    """A Win for a window that takes up room on screen, or None for everything else."""
    if not _IsWindowVisible(hwnd) or _IsIconic(hwnd):
        return None
    ex = _GetWindowLongPtr(hwnd, GWL_EXSTYLE)
    if ex & WS_EX_TRANSPARENT or _cloaked(hwnd):
        return None  # click-through overlays and windows parked on another virtual desktop
    pid = pid_of(hwnd)
    if pid == own_pid:
        return None
    cls = class_name(hwnd)
    if cls in SHELL_CLASSES:
        return None
    rect = frame(hwnd)
    if rect is None or rect.width < 1 or rect.height < 1:
        return None
    perch = (
        not ex & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        and rect.width >= 240
        and rect.height >= 120
        and not _GetWindow(hwnd, GW_OWNER)
    )
    return Win(int(hwnd), rect, pid, cls, perch)


def windows(own_pid: int = 0) -> list:
    """Windows that take up room on screen, top of the z-order first."""
    own_pid = own_pid or os.getpid()
    out: list = []

    def each(hwnd, _lparam):
        win = _describe(hwnd, own_pid)
        if win:
            out.append(win)
        return True

    _EnumWindows(WNDENUMPROC(each), 0)
    return out


def foreground() -> int:
    """The top-level window the person is typing into, or 0."""
    hwnd = _GetForegroundWindow()
    if not hwnd:
        return 0
    return int(_GetAncestor(hwnd, GA_ROOT) or hwnd)


def main_window_of(hwnd: int) -> int:
    """A dialog belongs to the window that owns it: climb to that one."""
    for _ in range(8):
        owner = _GetWindow(hwnd, GW_OWNER)
        if not owner or not _IsWindowVisible(owner):
            break
        hwnd = int(owner)
    return int(hwnd)


def active_window(own_pid: int = 0):
    """The app window the person works in right now, as a Win; None for the desktop,
    the taskbar, our own windows and anything too small to sit on."""
    hwnd = foreground()
    if not hwnd:
        return None
    win = _describe(main_window_of(hwnd), own_pid or os.getpid())
    return win if win and win.perch else None


def process_path(pid: int) -> str:
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if _QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _CloseHandle(handle)


def app_of_window(hwnd: int) -> tuple:
    """(pid, exe path) of the program behind a window. Store apps are all hosted by one
    frame process, so for those the real program is found among the child windows."""
    pid = pid_of(hwnd)
    path = process_path(pid)
    if os.path.basename(path).lower() == "applicationframehost.exe":
        found: list = []

        def each(child, _lparam):
            child_pid = pid_of(child)
            if child_pid and child_pid != pid:
                found.append(child_pid)
                return False
            return True

        _EnumChildWindows(hwnd, WNDENUMPROC(each), 0)
        if found:
            pid = found[0]
            path = process_path(pid) or path
    return pid, path


_descriptions: dict = {}


def file_description(path: str) -> str:
    """The program's own name from its exe ("Microsoft Excel"), or '' if it has none."""
    if path in _descriptions:
        return _descriptions[path]
    name = ""
    try:
        size = _GetFileVersionInfoSizeW(path, None)
        if size:
            data = ctypes.create_string_buffer(size)
            if _GetFileVersionInfoW(path, 0, size, data):
                ptr = ctypes.c_void_p()
                length = wt.UINT(0)
                if _VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 4:
                    lang, codepage = (ctypes.c_ushort * 2).from_address(ptr.value)
                    key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
                    if _VerQueryValueW(data, key, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                        name = ctypes.wstring_at(ptr.value, length.value).rstrip("\0").strip()
    except OSError:
        name = ""
    if len(name) > 60:
        name = ""
    if len(_descriptions) > 500:
        _descriptions.clear()
    _descriptions[path] = name
    return name


def bring_to_front(hwnd: int) -> bool:
    if not is_window(hwnd):
        return False
    if _IsIconic(hwnd):
        _ShowWindow(hwnd, SW_RESTORE)
    return bool(_SetForegroundWindow(hwnd))


def take_focus(hwnd: int) -> bool:
    """Give one of our own windows the keyboard, for the box you type a question into.

    Windows lets a program put itself in front only right after the person did something
    with it. A shortcut key pressed in another program counts; when Windows still says no,
    a tap of the Alt key (pressed and let go at once, by us) makes it say yes."""
    if not is_window(hwnd):
        return False
    if _SetForegroundWindow(hwnd):
        return True
    try:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
    except (AttributeError, OSError):
        return False
    return bool(_SetForegroundWindow(hwnd))


def window_of_exe(path: str) -> int:
    """A visible window of the program at `path`, or 0."""
    want = os.path.normcase(path)
    for win in windows():
        if win.perch and os.path.normcase(process_path(win.pid)) == want:
            return win.hwnd
    return 0


# --------------------------------------------------------------------------- our own windows

def top_level(child_hwnd: int) -> int:
    return int(_GetAncestor(child_hwnd, GA_ROOT) or child_hwnd)


def make_overlay(hwnd: int) -> None:
    """Never takes keyboard focus, stays out of Alt+Tab and the taskbar."""
    ex = _GetWindowLongPtr(hwnd, GWL_EXSTYLE)
    _SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    _SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def set_click_through(hwnd: int, on: bool) -> None:
    ex = _GetWindowLongPtr(hwnd, GWL_EXSTYLE)
    want = ex | WS_EX_TRANSPARENT if on else ex & ~WS_EX_TRANSPARENT
    if want != ex:
        _SetWindowLongPtr(hwnd, GWL_EXSTYLE, want)


def place(hwnd: int, x: int, y: int) -> None:
    _SetWindowPos(hwnd, None, int(x), int(y), 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def keep_on_top(hwnd: int) -> None:
    _SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def show(hwnd: int, visible: bool) -> None:
    _ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)


def exclude_from_capture(hwnd: int, on: bool) -> bool:
    """Keep a window out of screenshots, recordings and screen sharing."""
    try:
        return bool(user32.SetWindowDisplayAffinity(wt.HWND(hwnd), wt.DWORD(WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE)))
    except (AttributeError, OSError):
        return False


def voice_typing() -> None:
    """Open Windows' own voice typing for the field that has the keyboard (Windows key + H)."""
    for key, flag in ((0x5B, 0), (0x48, 0), (0x48, 2), (0x5B, 2)):
        user32.keybd_event(key, 0, flag, 0)
