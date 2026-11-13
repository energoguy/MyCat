"""Development helper: run a program on a Windows desktop of its own.

    python tools/apart.py <log file> <program> [arguments...]

Windows can hold several "desktops" at once; only one is on the screen and has the
keyboard and the mouse. A program started on another one opens its windows there: nobody
sees them, they cannot take the keyboard from whoever is working at this computer, and
nothing that person types or clicks can reach them. That is the place for the
walk-through (tools/selftest.py), which opens every window of the app and presses keys in
them:

    python tools/apart.py out/log.txt python tools/selftest.py out --apart

What the program prints goes to the log file. This helper waits for it and leaves with
its exit code. The desktop goes away with the last program on it.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

NAME = "MyCatCheck"
GENERIC_ALL = 0x10000000
STARTF_USESTDHANDLES = 0x00000100
CREATE_NO_WINDOW = 0x08000000
HANDLE_FLAG_INHERIT = 1
INFINITE = 0xFFFFFFFF
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
CREATE_ALWAYS = 2

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]


user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def run(log: str, command: list) -> int:
    desktop = user32.CreateDesktopW(NAME, None, None, 0, GENERIC_ALL, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    inherit = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    out = kernel32.CreateFileW(log, GENERIC_WRITE, FILE_SHARE_READ, ctypes.byref(inherit), CREATE_ALWAYS, 0, None)
    if out in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    start = STARTUPINFOW()
    start.cb = ctypes.sizeof(start)
    start.lpDesktop = "WinSta0\\" + NAME
    start.dwFlags = STARTF_USESTDHANDLES
    start.hStdOutput = start.hStdError = out
    made = PROCESS_INFORMATION()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
    try:
        if not kernel32.CreateProcessW(None, line, None, None, True, CREATE_NO_WINDOW, None, None, ctypes.byref(start), ctypes.byref(made)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel32.WaitForSingleObject(made.hProcess, INFINITE)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(made.hProcess, ctypes.byref(code))
        kernel32.CloseHandle(made.hThread)
        kernel32.CloseHandle(made.hProcess)
        return code.value
    finally:
        kernel32.CloseHandle(out)
        user32.CloseDesktop(desktop)


# ---------------------------------------------------------------------------------------
# Pictures. A desktop that is not on the screen cannot be photographed by copying the
# screen. But each window can be asked to draw itself, and the drawings can be laid over
# one another the way the windows lie there. (Used by the walk-through; needs Pillow.)

PW_RENDERFULLCONTENT = 2
LWA_COLORKEY, LWA_ALPHA = 1, 2
DESK = (214, 221, 230)  # what shows where no window is


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_ENUM, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowDC.restype = wintypes.HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD)]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


def own_windows() -> list:
    """This program's windows that are showing, the one on top first: (handle, left, top, right, bottom)."""
    mine = kernel32.GetCurrentProcessId()
    found: list = []

    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        rect = wintypes.RECT()
        if owner.value == mine and user32.IsWindowVisible(hwnd) and user32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
            found.append((hwnd, rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(_ENUM(each), 0)
    return found


def drawn(hwnd: int, width: int, height: int):
    """One window as it draws itself, and what of it is to be seen: (picture, mask)."""
    from PIL import Image, ImageChops

    key, alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(255), wintypes.DWORD()
    layered = bool(user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)))
    keyed = layered and bool(flags.value & LWA_COLORKEY)  # one colour of it stands for "nothing here": the cat, its bubble

    window = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(window)
    bitmap = gdi32.CreateCompatibleBitmap(window, width, height)
    before = gdi32.SelectObject(memory, bitmap)
    # Drawn the plain way, such a window still has that colour in it and can be cut out
    # along it; drawn the full way it comes with black in its place.
    user32.PrintWindow(hwnd, memory, 0 if keyed else PW_RENDERFULLCONTENT)
    gdi32.SelectObject(memory, before)
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(hwnd, window)
    shot = Image.frombuffer("RGB", (width, height), pixels, "raw", "BGRX", 0, 1)

    mask = Image.new("L", (width, height), alpha.value if layered and flags.value & LWA_ALPHA else 255)
    if keyed:
        colour = (key.value & 0xFF, (key.value >> 8) & 0xFF, (key.value >> 16) & 0xFF)
        same = ImageChops.difference(shot, Image.new("RGB", shot.size, colour)).convert("L").point(lambda v: 0 if v == 0 else 255)
        mask = ImageChops.multiply(mask, same)
    elif height > 80 and width > 80:
        # A window with a frame to pull at is a few points larger than it looks. That rim
        # (left, right and below) comes out black, and is left out.
        dark = shot.convert("L").point(lambda v: 255 if v else 0)
        middle = (height // 2, height // 2 + 24)

        def rim(columns) -> int:
            count = 0
            for x in columns:
                if dark.crop((x, middle[0], x + 1, middle[1])).getbbox() is not None:
                    break
                count += 1
            return count

        left, right = rim(range(0, 12)), rim(range(width - 1, width - 13, -1))
        below = 0
        for y in range(height - 1, height - 13, -1):
            if dark.crop((width // 2 - 12, y, width // 2 + 12, y + 1)).getbbox() is not None:
                break
            below += 1
        if left or right or below:
            inner = Image.new("L", (width, height), 0)
            box = (left, 0, width - right, height - below)
            inner.paste(mask.crop(box), box[:2])
            mask = inner
    return shot, mask


def photograph(box):
    """What this program's windows show inside `box` (left, top, right, bottom on its
    desktop), as a picture."""
    from PIL import Image

    left, top, right, bottom = box
    sheet = Image.new("RGB", (max(1, right - left), max(1, bottom - top)), DESK)
    for hwnd, x0, y0, x1, y1 in reversed(own_windows()):  # the one at the bottom first
        if x1 <= left or x0 >= right or y1 <= top or y0 >= bottom:
            continue
        shot, mask = drawn(hwnd, x1 - x0, y1 - y0)
        sheet.paste(shot, (x0 - left, y0 - top), mask)
    return sheet


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(run(sys.argv[1], sys.argv[2:]))
