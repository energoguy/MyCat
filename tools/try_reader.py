"""Development check: what can the cat read of the windows that are open?

    python tools/try_reader.py            for every program with a window up now: how much text
                                          could be read and how long it took. Counted only:
                                          not one word of it is printed or kept.
    python tools/try_reader.py own        opens a small window of its own (some words, a field,
                                          a password field), reads it back and shows what came

The first form is for finding out which programs let themselves be read at all. It is safe
to run with your own chats and mail open: it prints numbers.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workcat import reader, win32  # noqa: E402

TITLE = "MyCat reader check"
SHOWN = "The quarterly report is due on Friday."
TYPED = "Ask Aziz about the invoice"
SECRET = "hunter2-not-a-real-secret"


def window() -> None:
    """(The helper.) A plain window with words, a field and a password field, for half a minute."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    overlapped, visible, child, border, password = 0x00CF0000, 0x10000000, 0x40000000, 0x00800000, 0x0020
    top = user32.CreateWindowExW(0, "STATIC", TITLE, overlapped | visible, 120, 120, 460, 240, None, None, None, None)
    user32.CreateWindowExW(0, "STATIC", SHOWN, child | visible, 16, 16, 400, 24, top, None, None, None)
    user32.CreateWindowExW(0, "EDIT", TYPED, child | visible | border, 16, 56, 400, 26, top, None, None, None)
    user32.CreateWindowExW(0, "EDIT", SECRET, child | visible | border | password, 16, 96, 400, 26, top, None, None, None)
    message = wt.MSG()
    until = time.monotonic() + 30
    while time.monotonic() < until:
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        time.sleep(0.01)


def started():
    """Start the helper and wait for its window: (process, hwnd)."""
    helper = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--window"])
    find = ctypes.WinDLL("user32").FindWindowW
    find.restype = wt.HWND
    find.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    for _ in range(100):
        hwnd = find(None, TITLE)
        if hwnd:
            time.sleep(0.2)
            return helper, int(hwnd)
        time.sleep(0.05)
    helper.kill()
    raise SystemExit("the helper's window did not come up")


def own() -> int:
    helper, hwnd = started()
    try:
        seen = reader.read(hwnd)
        if "picture" in sys.argv:
            started_at = time.monotonic()
            words = reader.picture_text(hwnd)
            print(f"from its picture alone, in {time.monotonic() - started_at:.2f} s: {words!r}")
    finally:
        helper.kill()
    print(f"read ({seen.how}) in {seen.took:.2f} s from {seen.name!r} ({seen.program}), window {seen.title!r}:")
    print(seen.text or f"(nothing: {seen.why})")
    wrong = [what for what, ok in (("the words", SHOWN in seen.text), ("the field", TYPED in seen.text), ("the password stays out", SECRET not in seen.text)) if not ok]
    print("as it should be" if not wrong else f"NOT right: {wrong}")
    return 1 if wrong else 0


def count() -> int:
    """Numbers only. Nothing that was read is printed, kept or written anywhere."""
    print(f"{'program':28} {'characters':>10} {'words':>7} {'lines':>6} {'seconds':>8}   note")
    for program, name, hwnd in reader.showing():
        seen = reader.read(hwnd)
        text = seen.text
        letters = sum(1 for ch in text if ch.isalpha())
        note = ("from its picture; " if seen.how == "picture" else "") + seen.why or ("mostly not letters" if text and letters < len(text) * 0.4 else "")
        print(f"{(name + ' (' + program + ')')[:28]:28} {len(text):>10} {len(text.split()):>7} {len(text.splitlines()):>6} {seen.took:>8.2f}   {note} [{win32.class_name(hwnd)[:28]}]")
        del seen, text
    return 0


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>MyCat reader check page</title></head>
<body style="font-family: Segoe UI; margin: 24px">
<h1>Team chat</h1>
<ul>
<li><b>Aziz</b>: Can you send the weekly report today? <i>14:05</i></li>
<li><b>Дилноза</b>: Ҳисобот тайёр, эртага юбораман. <i>14:07</i></li>
<li><b>Мария</b>: Проверь, пожалуйста, счёт до пятницы. <i>14:09</i></li>
</ul>
<p>Message: <input value="I will send it at five"> Password: <input type="password" value="hunter2-not-a-real-secret"></p>
<div style="height: 4000px"></div>
<p>Far below the fold: this line is not in view.</p>
</body></html>"""
BROWSERS = {
    "edge": (r"Microsoft\Edge\Application\msedge.exe", "msedge"),
    "chrome": (r"Google\Chrome\Application\chrome.exe", "chrome"),
}


def browser(which: str) -> int:
    """A browser with a page of this tool's own, in a throwaway guest profile that touches
    nothing of the person's own browser; read back and shown."""
    import os
    import shutil
    import tempfile

    relative, program = BROWSERS[which]
    places = [Path(os.environ.get(name, "")) / relative for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    exe = next((place for place in places if place.is_file()), None)
    if exe is None:
        print(f"{which}: not installed")
        return 0
    folder = Path(tempfile.mkdtemp(prefix="mycat-reader-"))
    page = folder / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    started = subprocess.Popen([str(exe), f"--user-data-dir={folder / 'profile'}", "--guest", "--no-first-run", "--no-default-browser-check", "--new-window", "--window-size=900,700", page.as_uri()])
    seen = None
    try:
        for _ in range(100):
            time.sleep(0.2)
            ours = [hwnd for stem, _name, hwnd in reader.showing() if stem == program and "reader check page" in win32.window_title(hwnd)]
            if ours:
                time.sleep(1.5)  # let the page be drawn
                seen = reader.read(ours[0])
                break
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(started.pid)], capture_output=True)
        for process in _children_using(folder):
            subprocess.run(["taskkill", "/F", "/PID", str(process)], capture_output=True)
        time.sleep(0.5)
        shutil.rmtree(folder, ignore_errors=True)
    if seen is None:
        print(f"{which}: its window did not come up")
        return 1
    print(f"{which}: read in {seen.took:.2f} s, {len(seen.text)} characters:")
    print(seen.text or f"(nothing: {seen.why})")
    checks = (
        ("a message", "Can you send the weekly report today?" in seen.text), ("Uzbek in Cyrillic", "Ҳисобот тайёр" in seen.text), ("Russian", "Проверь" in seen.text),
        ("the password stays out", "hunter2" not in seen.text), ("what is not in view stays out", "Far below the fold" not in seen.text),
    )
    wrong = [what for what, ok in checks if not ok]
    print("as it should be" if not wrong else f"NOT right: {wrong}")
    return 1 if wrong else 0


def _children_using(folder: Path) -> list:
    """Process numbers of browser processes started on our throwaway profile that outlived
    their parent (found by the profile's name in their command line)."""
    script = f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{folder.name}*' }} | ForEach-Object {{ $_.ProcessId }}"
    try:
        listed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(word) for word in listed.split() if word.isdigit()]


if __name__ == "__main__":
    if "--window" in sys.argv:
        window()
    elif "own" in sys.argv:
        sys.exit(own())
    elif len(sys.argv) > 2 and sys.argv[1] == "browser" and sys.argv[2] in BROWSERS:
        sys.exit(browser(sys.argv[2]))
    else:
        sys.exit(count())
