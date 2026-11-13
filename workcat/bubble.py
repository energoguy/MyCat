"""The cat's speech bubble, and the queue that decides when it may speak.

A bubble never takes keyboard focus. Clicking it closes it; it can carry up to three
buttons. Outside its rounded shape the window is see-through and clicks pass through.
"""
from __future__ import annotations

import logging
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from tkinter import font as tkfont

from . import win32, world
from .overlay import KEY, Overlay

log = logging.getLogger("workcat")

INK = "#2b2e3b"
PAPER = "#fffdf6"
PRIMARY = "#ffcf4a"
PRIMARY_HOT = "#ffdd7a"
PLAIN = "#eceef3"
PLAIN_HOT = "#dfe3ec"


def pixel_box(canvas: tk.Canvas, x0: int, y0: int, x1: int, y1: int, u: int, fill: str, edge: str, tags=()) -> None:
    """A rectangle with stepped pixel-art corners: an edge `u` thick around a fill."""
    def shape(a0, b0, a1, b1, colour):
        for dx, dy in ((2 * u, 0), (0, 2 * u), (u, u)):
            canvas.create_rectangle(a0 + dx, b0 + dy, a1 - dx, b1 - dy, fill=colour, outline="", tags=tags)

    shape(x0, y0, x1, y1, edge)
    shape(x0 + u, y0 + u, x1 - u, y1 - u, fill)


class Bubble:
    def __init__(self, app):
        self.app = app
        s = app.ui_scale
        self.u = max(2, round(2 * s))
        self.pad = round(11 * s)
        self.wrap = round(250 * s)
        self.gap = round(6 * s)
        self.win = Overlay(app.root, 20, 20)
        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.font = tkfont.Font(root=app.root, family="Segoe UI", size=10)
        self.bold = tkfont.Font(root=app.root, family="Segoe UI", size=9, weight="bold")
        self.canvas.bind("<Button-1>", self._clicked)
        self.canvas.bind("<Enter>", lambda e: self._hold())
        self.canvas.bind("<Leave>", lambda e: self._release())
        self.shown = False
        self.on_close = None
        self.timer = None
        self.ttl = 0.0
        self.tail = True
        self.button_hit = False
        self.shape = (0, 0)  # width and height of the bubble body
        self.anchor = None
        self.apply_capture()

    def apply_capture(self) -> None:
        win32.exclude_from_capture(self.win.hwnd, bool(self.app.settings.get("hide_from_capture", True)))

    # ------------------------------------------------------------------ showing

    def show(self, text: str, buttons=(), ttl: float = 10.0, on_close=None) -> None:
        """buttons: (label, callback) pairs; the first one is drawn as the main choice."""
        self.hide(notify=False)
        c = self.canvas
        c.delete("all")
        u, pad = self.u, self.pad
        # "40 %" and "9 °C" stay on one line: a no-break space between the number and its sign
        drawn = text.replace(" %", "\u00a0%").replace(" °C", "\u00a0°C")
        label = c.create_text(pad, pad, text=drawn, width=self.wrap, anchor="nw", font=self.font, fill=INK)
        x0, y0, x1, y1 = c.bbox(label)
        text_w, text_h = x1 - x0, y1 - y0

        line = self.bold.metrics("linespace")
        bh = line + round(8 * self.app.ui_scale)
        sizes = [self.bold.measure(name) + round(18 * self.app.ui_scale) for name, _ in buttons]
        rows: list = [[]]
        used = 0
        for i, w in enumerate(sizes):  # wrap the buttons into as many rows as they need
            if rows[-1] and used + self.gap + w > max(self.wrap, text_w):
                rows.append([])
                used = 0
            used += (self.gap if rows[-1] else 0) + w
            rows[-1].append(i)
        row_w = [sum(sizes[i] for i in row) + self.gap * (len(row) - 1) for row in rows if row]
        buttons_h = (bh + self.gap) * len(row_w)
        inner_w = max([text_w, round(90 * self.app.ui_scale)] + row_w)
        width = inner_w + 2 * pad
        height = text_h + buttons_h + 2 * pad
        self.shape = (width, height)

        pixel_box(c, 0, 0, width, height, u, PAPER, INK, tags=("body",))
        c.tag_raise(label)
        y = pad + text_h + self.gap
        for row in rows:
            x = pad
            for i in row:
                self._button(x, y, sizes[i], bh, buttons[i][0], buttons[i][1], primary=(i == 0))
                x += sizes[i] + self.gap
            if row:
                y += bh + self.gap

        self.on_close = on_close
        self.ttl = ttl
        self.shown = True
        self.anchor = None
        self.follow(force=True)
        self.win.set_visible(True)
        self._arm(ttl)

    def _button(self, x: int, y: int, w: int, h: int, name: str, callback, primary: bool) -> None:
        c = self.canvas
        tag = f"b{x}_{y}"
        fill, hot = (PRIMARY, PRIMARY_HOT) if primary else (PLAIN, PLAIN_HOT)
        u = max(1, self.u // 2)
        pixel_box(c, x, y, x + w, y + h, u, fill, INK, tags=(tag, tag + "f"))
        c.create_text(x + w // 2, y + h // 2, text=name, font=self.bold, fill=INK, tags=(tag,))
        faces = [i for i in c.find_withtag(tag + "f")][3:6]  # the three fill rectangles

        def paint(colour):
            for item in faces:
                c.itemconfigure(item, fill=colour)

        def press(_event):
            self.button_hit = True
            self.hide(notify=False)
            try:
                callback()
            except Exception:
                log.exception("bubble button %r", name)

        c.tag_bind(tag, "<Enter>", lambda e: (paint(hot), c.configure(cursor="hand2")))
        c.tag_bind(tag, "<Leave>", lambda e: (paint(fill), c.configure(cursor="")))
        c.tag_bind(tag, "<Button-1>", press)

    def follow(self, force: bool = False) -> None:
        """Keep the bubble by the cat's head; called whenever the cat may have moved."""
        if not self.shown:
            return
        anchor = self.app.pet.head()
        if not force and anchor == self.anchor:
            return
        self.anchor = anchor
        ax, ay = anchor
        width, height = self.shape
        u = self.u
        tail_h = 3 * u
        monitor = world.monitor_at(ax, max(ay, 0), self.app.pet.monitors)
        area = monitor.work if monitor else win32.Rect(0, 0, 1920, 1080)
        edge = round(6 * self.app.ui_scale)
        c = self.canvas
        c.delete("tail")
        if ay - height - tail_h >= area.top + edge:  # above the head, with a tail pointing down
            x = min(max(ax - width // 2, area.left + edge), area.right - width - edge)
            y = ay - height - tail_h
            tx = min(max(ax - x, 5 * u), width - 5 * u)
            for i, half in enumerate((2, 1, 0)):
                top = height - u + i * u
                c.create_rectangle(tx - (half + 1) * u, top, tx + (half + 1) * u, top + u, fill=INK, outline="", tags="tail")
                if half:
                    c.create_rectangle(tx - half * u, top, tx + half * u, top + u, fill=PAPER, outline="", tags="tail")
            self.win.set_box(width, height + tail_h, x, y)
        else:  # no room above: beside the cat
            left, top, right, _bottom = self.app.pet.box()
            x = left - width - edge if left - width - edge >= area.left + edge else right + edge
            x = min(max(x, area.left + edge), area.right - width - edge)
            y = min(max(top, area.top + edge), area.bottom - height - edge)
            self.win.set_box(width, height, x, y)

    # ------------------------------------------------------------------ closing

    def hide(self, notify: bool = True) -> None:
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
            self.timer = None
        if not self.shown:
            return
        self.shown = False
        # Wipe it while it is still on screen: Windows keeps the last picture of a hidden
        # window and would flash the old words for an instant the next time it appears.
        self.canvas.delete("all")
        self.canvas.update_idletasks()
        self.win.set_visible(False)
        self.win.move(-9000, -9000)
        callback, self.on_close = self.on_close, None
        if notify and callback:
            try:
                callback()
            except Exception:
                log.exception("bubble close")

    def _arm(self, seconds: float) -> None:
        if self.timer is not None:
            self.app.root.after_cancel(self.timer)
        self.timer = self.app.root.after(int(seconds * 1000), self.hide)

    def _hold(self) -> None:
        if self.shown and self.timer is not None:
            self.app.root.after_cancel(self.timer)
            self.timer = None

    def _release(self) -> None:
        if self.shown:
            self._arm(4.0)

    def _clicked(self, _event) -> None:
        if self.button_hit:  # the button already handled this click
            self.button_hit = False
            return
        self.hide()


@dataclass
class Line:
    text: str
    buttons: tuple = ()
    ttl: float = 10.0
    kind: str = "chat"  # reply, alert, nudge or chat
    emote: str = "talk"
    on_close: object = None
    born: float = field(default_factory=time.monotonic)


# How long a line may wait for a quiet moment before it is no longer worth saying.
SHELF_LIFE = {"reply": 30, "alert": 2 * 3600, "nudge": 20 * 60, "chat": 90}


class Voice:
    """Everything the cat says goes through here, one bubble at a time.

    reply  an answer to something you just did: shown at once
    alert  a reminder you asked for: waits only while the screen is busy
    nudge  a suggestion: also waits while you focus or are in a call
    chat   small talk: dropped rather than queued
    """

    def __init__(self, app):
        self.app = app
        self.bubble = Bubble(app)
        self.queue: deque = deque()

    def say(self, text: str, buttons=(), ttl: float = 0.0, kind: str = "chat", emote: str = "", on_close=None) -> None:
        if not ttl:
            ttl = 9.0 + len(text) * 0.06 + (14.0 if buttons else 0.0)
        line = Line(text, tuple(buttons), ttl, kind, emote or ("alert" if kind == "alert" else "talk"), on_close)
        if kind == "reply":
            self.queue.appendleft(line)
        elif kind == "chat" and (self.queue or self.bubble.shown):
            return
        else:
            self.queue.append(line)
        self.pump()

    def allowed(self, kind: str) -> bool:
        if kind == "reply":
            return True
        quiet = self.app.quiet_level()
        if quiet == "hard":
            return False
        return quiet != "soft" or kind == "alert"

    def pump(self) -> None:
        """Show the next line if the moment allows. Called a few times a second."""
        now = time.monotonic()
        while self.queue and now - self.queue[0].born > SHELF_LIFE[self.queue[0].kind]:
            self.queue.popleft()
        self.bubble.follow()
        if not self.queue:
            return
        line = self.queue[0]
        if self.bubble.shown and line.kind != "reply":
            return
        if not self.allowed(line.kind):
            return
        self.queue.popleft()
        self.bubble.show(line.text, line.buttons, line.ttl, line.on_close)
        self.app.pet.emote(line.emote, 1.4 if line.emote == "talk" else 2.4)

    def hush(self) -> None:
        self.bubble.hide()

    def busy(self) -> bool:
        return self.bubble.shown or bool(self.queue)
