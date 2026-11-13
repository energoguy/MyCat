"""The ask box: one line to type in, right by the cat.

Double-click the cat, press the shortcut key, or pick "Ask me" in its menu. Type,
press Enter, and the cat answers in its speech bubble. Without the AI the same box
adds a task.

Unlike the cat's other windows this one takes the keyboard: that is its whole point.
It goes away on Enter, on Esc, and when you click anywhere else.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

from . import win32, world

INK = "#2b2e3b"
PAPER = "#fffdf6"
FAINT = "#8a8fa0"


class QuickBox:
    def __init__(self, app):
        self.app = app
        self.win = None
        self.entry = None
        self.var = None
        self.then = None
        self.last = ""  # what was typed last time: the Up key brings it back
        self.tick = None  # the tick under the field, when there is one ("With what Telegram shows")
        self.ticked = False  # ... and whether it was set when Enter was pressed

    @property
    def open(self) -> bool:
        return self.win is not None

    def show(self, hint: str, then, text: str = "", tick: str = "") -> None:
        """Open the box. `hint` is the small line under it; `then(text)` gets what was typed.
        `tick`: the words of a tick under the field, off until the person sets it; whether
        they did is in `ticked` when `then` is called."""
        self.close()
        self.tick, self.ticked = None, False
        app = self.app
        s = app.ui_scale
        self.then = then
        win = self.win = tk.Toplevel(app.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=INK)
        edge = max(2, round(2 * s))
        body = tk.Frame(win, bg=PAPER)
        body.pack(padx=edge, pady=edge)
        self.var = tk.StringVar(value=text)
        entry = self.entry = tk.Entry(
            body, textvariable=self.var, width=40, relief="flat", bd=0, highlightthickness=0, bg=PAPER, fg=INK,
            insertbackground=INK, font=tkfont.Font(root=win, family="Segoe UI", size=11),
        )
        entry.pack(padx=round(10 * s), pady=(round(9 * s), round(2 * s)))
        entry.icursor("end")
        small = tkfont.Font(root=win, family="Segoe UI", size=8)
        if tick:
            self.tick = tk.BooleanVar(master=win, value=False)
            box = tk.Checkbutton(
                body, text=tick, variable=self.tick, font=tkfont.Font(root=win, family="Segoe UI", size=9), bg=PAPER, fg=INK, activebackground=PAPER,
                activeforeground=INK, selectcolor=PAPER, anchor="w", bd=0, highlightthickness=0, padx=0, pady=0, cursor="hand2",
            )
            box.pack(fill="x", padx=round(8 * s), pady=(0, round(2 * s)))
            box.bind("<Return>", self._enter)
            box.bind("<Escape>", lambda e: self.close())
            entry.bind("<Control-space>", lambda e: (self.tick.set(not self.tick.get()), "break")[1])  # without leaving the field
        tk.Label(body, text=hint, font=small, bg=PAPER, fg=FAINT, anchor="w", justify="left", wraplength=round(330 * s)).pack(fill="x", padx=round(10 * s), pady=(0, round(7 * s)))
        entry.bind("<Return>", self._enter)
        entry.bind("<KP_Enter>", self._enter)
        entry.bind("<Escape>", lambda e: self.close())
        entry.bind("<Up>", self._again)
        win.bind("<FocusOut>", lambda e: win.after(150, self._left))
        win.update_idletasks()
        x, y = self._spot(win.winfo_reqwidth(), win.winfo_reqheight())
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win32.exclude_from_capture(win32.top_level(win.winfo_id()), bool(app.settings.get("hide_from_capture", True)))
        self._focus()
        win.after(90, self._focus)

    def _spot(self, width: int, height: int) -> tuple:
        """Above the cat's head; below it if there is no room; at the mouse pointer when
        the cat is hidden."""
        app = self.app
        gap = round(8 * app.ui_scale)
        if app.pet.hidden:
            x, y = win32.cursor()
            top, bottom = y - height - gap, y + gap
        else:
            x, head = app.pet.head()
            top, bottom = head - height - gap, int(app.pet.feet) + gap
        monitor = world.monitor_at(x, max(top, 0), app.pet.monitors)
        area = monitor.work if monitor else win32.Rect(0, 0, 1920, 1080)
        y = top if top >= area.top + gap else bottom
        x = min(max(x - width // 2, area.left + gap), area.right - width - gap)
        return x, min(max(y, area.top + gap), area.bottom - height - gap)

    def _focus(self) -> None:
        if self.win is None or not self.win.winfo_exists():
            return
        self.win.lift()
        win32.take_focus(win32.top_level(self.win.winfo_id()))
        self.entry.focus_force()

    def _left(self) -> None:
        """The keyboard went to another window: the box has had its turn."""
        if self.win is not None and self.win.winfo_exists() and self.win.focus_displayof() is None:
            self.close()

    def _again(self, _event) -> str:
        if self.last and not self.var.get():
            self.var.set(self.last)
            self.entry.icursor("end")
        return "break"

    def _enter(self, _event) -> str:
        text = self.var.get().strip()
        then = self.then
        self.ticked = bool(self.tick is not None and self.tick.get())
        self.close()
        if text and then:
            self.last = text
            then(text)
        return "break"

    def close(self) -> None:
        win, self.win = self.win, None
        self.then = None
        if win is not None and win.winfo_exists():
            win.destroy()
