"""The cat's own popup menu, used for a right-click on the cat and on the tray icon.

A native menu needs keyboard focus to close properly, and taking focus is exactly what
the cat must never do while you type. This one is a small overlay window instead: it
closes when you click anywhere else or press Esc.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import font as tkfont

from . import win32, world
from .overlay import Overlay

log = logging.getLogger("workcat")

INK = "#2b2e3b"
PAPER = "#fffdf6"
HOT = "#ffe7a3"
FAINT = "#8a8fa0"
RULE = "#e3e1d8"


class Menu:
    def __init__(self, app):
        self.app = app
        self.win = None
        self.armed = False
        self.poll = None
        self.font = tkfont.Font(root=app.root, family="Segoe UI", size=10)
        self.small = tkfont.Font(root=app.root, family="Segoe UI", size=8)

    def popup(self, x: int, y: int, items: list) -> None:
        """items: (label, callback) to choose, (label, None) for a heading, None for a rule.
        A label may be 'Text\\thint': the hint is shown small on the right."""
        self.close()
        s = self.app.ui_scale
        win = Overlay(self.app.root, 20, 20, see_through=False)
        win.configure(bg=INK)
        body = tk.Frame(win, bg=PAPER)
        body.pack(padx=max(1, round(s)), pady=max(1, round(s)))
        for item in items:
            if item is None:
                tk.Frame(body, bg=RULE, height=1).pack(fill="x", padx=round(8 * s), pady=round(3 * s))
                continue
            text, callback = item
            text, _, hint = text.partition("\t")
            row = tk.Frame(body, bg=PAPER)
            row.pack(fill="x")
            if callback is None:
                tk.Label(row, text=text, bg=PAPER, fg=FAINT, font=self.small, anchor="w", padx=round(12 * s), pady=round(3 * s)).pack(fill="x")
                continue
            name = tk.Label(row, text=text, bg=PAPER, fg=INK, font=self.font, anchor="w", padx=round(12 * s), pady=round(4 * s))
            name.pack(side="left", fill="x", expand=True)
            parts = [row, name]
            if hint:
                extra = tk.Label(row, text=hint, bg=PAPER, fg=FAINT, font=self.small, anchor="e", padx=round(12 * s))
                extra.pack(side="right")
                parts.append(extra)
            for part in parts:
                part.configure(cursor="hand2")
                part.bind("<Enter>", lambda e, p=parts: [w.configure(bg=HOT) for w in p])
                part.bind("<Leave>", lambda e, p=parts: [w.configure(bg=PAPER) for w in p])
                part.bind("<ButtonRelease-1>", lambda e, cb=callback: self._pick(cb))
        win.update_idletasks()
        width = max(body.winfo_reqwidth() + 2 * max(1, round(s)), round(170 * s))
        height = body.winfo_reqheight() + 2 * max(1, round(s))
        body.pack_configure(fill="both", expand=True)
        monitor = world.monitor_at(x, y, win32.monitors())
        area = monitor.work if monitor else win32.Rect(0, 0, 1920, 1080)
        left = x if x + width <= area.right else x - width
        top = y if y + height <= area.bottom else y - height
        left = min(max(left, area.left), max(area.left, area.right - width))
        top = min(max(top, area.top), max(area.top, area.bottom - height))
        win.set_box(width, height, left, top)
        win.set_visible(True)
        self.win = win
        self.armed = False
        self._watch()

    def _watch(self) -> None:
        """Close on a click anywhere else, or on Esc. The click that opened the menu is
        still held down at first, so nothing counts until the buttons are up once."""
        if self.win is None:
            return
        down = win32.key_down(win32.VK_LBUTTON) or win32.key_down(win32.VK_RBUTTON)
        if not self.armed:
            self.armed = not down
        elif win32.key_down(win32.VK_ESCAPE):
            self.close()
            return
        elif down:
            x, y = win32.cursor()
            x0, y0, x1, y1 = self.win.box()
            if not (x0 <= x < x1 and y0 <= y < y1):
                self.close()
                return
        self.poll = self.app.root.after(40, self._watch)

    def _pick(self, callback) -> None:
        self.close()
        self.app.root.after(30, lambda: self._run(callback))

    @staticmethod
    def _run(callback) -> None:
        try:
            callback()
        except Exception:
            log.exception("menu item")

    def close(self) -> None:
        if self.poll is not None:
            self.app.root.after_cancel(self.poll)
            self.poll = None
        if self.win is not None:
            self.win.destroy()
            self.win = None

    @property
    def open(self) -> bool:
        return self.win is not None
