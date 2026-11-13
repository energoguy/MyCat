"""Development check: does the cat sit on a window, ride it, and fall when it closes?

    python tools/try_window.py out_dir

Opens a small empty window of its own to sit on, moves it, closes it, and reports what the
cat did. Also checks that "keep me out of screenshots" really hides the cat, and how much
processor time the app uses while nothing happens. Needs Pillow for the pictures.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from workcat import sprites, win32, world  # noqa: E402
from workcat.app import App, setup_logging  # noqa: E402

out = Path(sys.argv[1])
data = out / "data"
shutil.rmtree(data, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
setup_logging(data)

HELPER = (
    "import tkinter as tk\n"
    "r = tk.Tk(); r.title('Seat test'); r.geometry('520x260+500+330'); r.configure(bg='#20242f')\n"
    "tk.Label(r, text='A window for the cat to sit on', fg='white', bg='#20242f').pack(expand=True)\n"
    "r.after(14000, r.destroy); r.mainloop()\n"
)
helper = subprocess.Popen([sys.executable, "-c", HELPER])
app = App(data, overrides={"first_run_done": True, "hide_from_capture": False, "follow_window": False, "chatter": "off"})
pet = app.pet
state: dict = {}
problems: list = []
cpu0 = time.process_time()
t0 = time.monotonic()


def helper_window():
    for win in win32.windows():
        if win.pid == helper.pid and win.perch:
            return win
    return None


def grab(name: str) -> None:
    x0, y0, x1, y1 = pet.box()
    ImageGrab.grab(bbox=(x0 - 60, y0 - 20, x1 + 60, y1 + 40), all_screens=True).save(out / f"{name}.png")


OUTLINE = bytes.fromhex(sprites.palette(app.settings["coat"])["o"][1:])


def cat_pixels() -> int:
    """How many pixels in the cat's box have the colour of its outline."""
    data = ImageGrab.grab(bbox=pet.box(), all_screens=True).convert("RGB").tobytes()
    return sum(1 for i in range(0, len(data), 3) if data[i:i + 3] == OUTLINE)


def step(label: str, fn) -> None:
    try:
        note = fn()
        print("ok  ", label, "" if note is None else f"-> {note}")
    except Exception:
        problems.append(label)
        print("FAIL", label)
        traceback.print_exc()


def jump_on():
    win = helper_window()
    assert win is not None, "helper window not found"
    state["hwnd"] = win.hwnd
    seat = world.window_seat(win.hwnd, win.rect, pet.monitors, pet.need, pet.margin)
    assert seat is not None, "no room above the helper window"
    pet._go(seat)
    return f"mode {pet.mode}, foreground is helper: {win32.foreground() == win.hwnd}"


def landed():
    rect = win32.frame(state["hwnd"])
    assert pet.mode == "rest", pet.mode
    assert pet.seat.kind == "window" and pet.seat.hwnd == state["hwnd"]
    assert abs(pet.feet - rect.top) < 1, (pet.feet, rect.top)
    grab("1_on_window")
    return f"feet {pet.feet:.0f} = window top {rect.top}, x {pet.x:.0f} within {rect.left}..{rect.right}"


def move_window():
    state["before"] = (pet.x, pet.feet)
    win32.place(state["hwnd"], 760, 420)


def rode():
    rect = win32.frame(state["hwnd"])
    dx, dy = pet.x - state["before"][0], pet.feet - state["before"][1]
    assert abs(pet.feet - rect.top) < 1 and abs(dx - 260) < 3 and abs(dy - 90) < 3, (dx, dy)
    grab("2_rode_along")
    return f"moved with the window by ({dx:.0f}, {dy:.0f})"


def follow_on():
    app.settings["follow_window"] = True
    pet.pinned = False
    state["active"] = win32.active_window()
    return f"an app window is active: {state['active'] is not None}"


def followed():
    active = win32.active_window()
    if active is None:
        return "nothing active to follow (skipped)"
    want = world.seat_for(active, pet.monitors, pet.need, pet.margin)
    assert pet._same_place(want), (pet.seat, want)
    return f"sits by the active window: {pet.seat.kind}"


def back_on_helper():
    app.settings["follow_window"] = False
    rect = win32.frame(state["hwnd"])
    pet._go(world.window_seat(state["hwnd"], rect, pet.monitors, pet.need, pet.margin))


def capture_hidden():
    seen = cat_pixels()
    app.settings["hide_from_capture"] = True
    worked = win32.exclude_from_capture(pet.win.hwnd, True)
    app.root.update()
    time.sleep(0.4)
    hidden = cat_pixels()
    win32.exclude_from_capture(pet.win.hwnd, False)
    app.settings["hide_from_capture"] = False
    pet.win.set_visible(False)  # what is behind the cat may happen to have that colour too
    app.root.update()
    time.sleep(0.3)
    behind = cat_pixels()
    pet.win.set_visible(True)
    assert seen - behind > 50, f"the cat was not visible to begin with ({seen}, {behind} behind it)"
    assert worked and hidden <= behind, f"still {hidden - behind} outline pixels in a screenshot (call returned {worked})"
    return f"cat outline pixels in a screenshot: {seen - behind} normally, {hidden - behind} when hidden"


def close_window():
    helper.terminate()


def fell():
    assert pet.mode == "rest" and pet.seat.kind == "floor", (pet.mode, pet.seat)
    grab("3_on_taskbar")
    return f"on the taskbar at {pet.feet:.0f}"


def cpu():
    used = time.process_time() - cpu0
    wall = time.monotonic() - t0
    return f"{used:.2f} s of processor time in {wall:.1f} s = {100 * used / wall:.1f}% of one core"


plan = [
    (1500, "leap onto a window", jump_on),
    (3200, "landed on its top edge", landed),
    (3300, "move that window", move_window),
    (3900, "rode along", rode),
    (4000, "turn following on", follow_on),
    (6400, "went to the active window", followed),
    (6500, "back onto the test window", back_on_helper),
    (8200, "hidden from screenshots", capture_hidden),
    (9000, "close the window", close_window),
    (10800, "fell to the taskbar", fell),
    (17000, "processor use", cpu),
    (17200, "quit", app.quit),
]
for ms, label, fn in plan:
    app.root.after(ms, lambda label=label, fn=fn: step(label, fn))
app.run()
if helper.poll() is None:
    helper.terminate()
print("problems:", problems or "none")
sys.exit(1 if problems else 0)
