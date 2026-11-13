"""The cat on the screen: where it sits, how it moves, what it shows.

It keeps company with the window you work in: it sits on that window's top edge and
rides along when the window moves. A window that reaches the top of the screen leaves no
room above it, so then the cat sits on the taskbar below it instead.

    rest  on a seat: sitting, working, sleeping
    walk  along the seat to another spot
    leap  through the air to another seat
    fall  down to a seat (let go by the mouse, or its window went away)
    drag  held by the mouse
"""
from __future__ import annotations

import logging
import math
import os
import random
import time
import tkinter as tk

from . import sprites, win32, world
from .overlay import KEY, Overlay
from .scene import look_of, rest_anim

log = logging.getLogger("workcat")

SETTLE = 1.2  # the active window must stay the same this long before the cat moves to it
SIDE_ANIMS = ("walk", "leap")
EYE = ("..xxxxx..", ".xwwowwx.", "xwwooowwx", ".xwwowwx.", "..xxxxx..")  # x: the line, w: white, o: the pupil


class Pet:
    def __init__(self, app):
        self.app = app
        self.scale = app.scale  # screen pixels per pixel of art
        self.size = sprites.SIZE * self.scale
        self.u = self.size / 32.0  # distances below are in these units: 3 px at the usual size
        self.sink = 2  # px the feet overlap the edge they stand on
        self.tall = (sprites.SIZE - sprites.SIT_TOP + 1) * self.scale  # the sitting cat, ear tips to feet
        self.need = self.tall  # room the cat needs above a window
        self.margin = int(20 * self.u)  # the cat's centre keeps this far from a window's corners
        self.pid = os.getpid()

        self.win = Overlay(app.root, self.size, self.size)
        self.canvas = tk.Canvas(self.win, width=self.size, height=self.size, bg=KEY, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack()
        self.item = self.canvas.create_image(0, 0, anchor="nw")
        self.image = None
        self.eye = None  # the little eye the cat wears while it may read other programs' windows
        self.eye_item = None
        self.apply_eye()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.app.quick_ask())
        self.canvas.bind("<Button-3>", lambda e: self.app.show_menu(e.x_root, e.y_root))

        now = time.monotonic()
        self.x = 0.0  # centre of the cat
        self.feet = 0.0  # the line its feet are on
        self.seat = None
        self.mode = "rest"
        self.facing = 1
        self.anim = "sit"
        self.anim_t0 = now
        self.emote_name = None
        self.emote_until = 0.0
        self.walk_to = 0.0
        self.flight = None
        self.fall_to = None
        self.vy = 0.0
        self.rel: dict = {}  # window -> how far left of the seat's right end the cat sits
        self.floor_x: dict = {}  # floor line -> where the cat was put
        self.want = None
        self.want_since = 0.0
        self.pinned = False  # put down by hand: stay until another window becomes active
        self.pin = 0
        self.hidden = False
        self.press = None
        self.dragging = False
        self.through = False
        self.monitors = win32.monitors()
        self.monitors_at = now
        self.next_look = 0.0
        self.next_top = 0.0
        self.next_stroll = now + random.uniform(50, 140)
        self.moved_at = 0.0
        self.last = now
        self.dead = False
        self.tuck = None  # (side, monitor) while tucked away at a side of the screen
        self.play_until = 0.0  # chasing the mouse pointer until then
        self.pounced_at = 0.0

        self.settle()
        self._tuck_again()
        self.apply_capture()
        self.win.set_visible(True)
        self.tick()

    # ------------------------------------------------------------------ public

    def emote(self, name: str, seconds: float) -> None:
        """Play a short reaction (happy, cheer, talk, alert, yawn) over whatever it does."""
        self.emote_name = name
        self.emote_until = time.monotonic() + seconds
        self.anim_t0 = time.monotonic() if self.anim != name else self.anim_t0

    def set_hidden(self, hidden: bool) -> None:
        if hidden == self.hidden:
            return
        self.hidden = hidden
        if not hidden:
            if self.tuck is None:  # a tucked cat comes back where it was tucked
                self.settle()
            self.draw(time.monotonic())
        self.win.set_visible(not hidden)

    def head(self) -> tuple:
        """Screen point just above the cat's head: where a speech bubble points."""
        x = self.x
        if self.tuck is not None:  # only half of it is on the screen: point at that half
            side, monitor = self.tuck
            x = monitor.rect.left + self.size / 4 if side == "left" else monitor.rect.right - self.size / 4
        return int(x), int(self.feet - self.tall - 2 * self.scale)

    # ------------------------------------------------------------------ tucked away, and play

    @property
    def tucked(self) -> bool:
        return self.tuck is not None

    def tuck_at(self, side: str, monitor, feet: float) -> dict:
        """Hide at a side of the screen with half the face looking round the edge.
        Returns what to remember so it can be found there again after a restart."""
        work = monitor.work
        self.tuck = (side, monitor)
        self.mode = "tucked"
        self.flight = self.fall_to = None
        self.play_until = 0.0
        self.want = None
        self.feet = float(min(max(feet, work.top + self.tall), work.bottom))
        shown = self.size // 2
        left = monitor.rect.left - self.size + shown if side == "left" else monitor.rect.right - shown
        self.x = left + self.size / 2
        index = self.monitors.index(monitor) if monitor in self.monitors else 0
        return {"side": side, "monitor": index, "at": round((self.feet - work.top) / max(work.bottom - work.top, 1), 4)}

    def untuck(self) -> None:
        """Come out from the edge and go to the window being worked in."""
        if self.tuck is None:
            return
        self.tuck = None
        self.mode = "rest"
        self.seat = None  # it was sitting nowhere: leap from where it is
        self.go_to_active()

    def _tuck_again(self) -> None:
        """Back to where it was tucked when the app last closed, if that edge still exists."""
        saved = self.app.settings.get("tucked") or {}
        side, index = saved.get("side"), saved.get("monitor", 0)
        if side not in ("left", "right") or not isinstance(index, int) or not 0 <= index < len(self.monitors):
            return
        monitor = self.monitors[index]
        edge = monitor.rect.left if side == "left" else monitor.rect.right - 1
        found = world.outer_edge(edge, monitor.work.top + 1, self.monitors, 2)
        if found is None or found[0] != side:
            return
        try:
            feet = monitor.work.top + float(saved.get("at", 0.5)) * (monitor.work.bottom - monitor.work.top)
        except (TypeError, ValueError):
            return
        self.tuck_at(side, monitor, feet)

    def _stay_tucked(self, now: float) -> None:
        if now - self.monitors_at <= 2.0:
            return
        self.monitors = win32.monitors() or self.monitors
        self.monitors_at = now
        side, monitor = self.tuck
        if not any(m.rect == monitor.rect for m in self.monitors):  # that screen was unplugged
            self.untuck()
            self.app.on_tucked(None)

    def start_play(self, seconds: float = 10.0) -> None:
        """Chase the mouse pointer along the line it sits on, for a little while."""
        self.play_until = time.monotonic() + seconds
        self.pounced_at = 0.0
        self.pinned = True  # stay on this seat while playing
        active = win32.active_window(self.pid)
        self.pin = active.hwnd if active else 0
        self.want = None

    def _play(self, now: float, dt: float) -> None:
        seat = self.seat
        if seat is None or now >= self.play_until:
            self.play_until = 0.0
            self.mode = "rest"
            self.app.on_play_over()
            return
        pointer = win32.cursor()[0]
        target = seat.clamp(pointer)
        gap = target - self.x
        stride = 1.7 * sprites.WALK_SPEED * self.scale * dt  # a run, not a walk
        if abs(gap) > max(stride, 3 * self.u):
            self.facing = 1 if gap > 0 else -1
            self.x += stride * self.facing
            self.mode = "walk"
            return
        self.mode = "rest"
        if abs(pointer - self.x) <= 12 * self.u and now - self.pounced_at >= 1.3:  # caught it
            self.pounced_at = now
            self.emote("cheer", 0.8)
            self.app.on_pounce()

    def box(self) -> tuple:
        return self.win.box()

    def apply_eye(self) -> None:
        """Show the eye while reading other programs is switched on, so that this is never
        on without a sign of it on the screen."""
        on = bool(self.app.settings.get("first_run_done") and self.app.settings.get("ai_may_read"))
        if on and self.eye is None:
            dot = max(2, self.scale)  # as large as the cat's own dots
            colours = {"x": "#2B2E3B", "w": "#FFFFFF", "o": "#2B2E3B"}
            self.eye = tk.PhotoImage(master=self.canvas, width=len(EYE[0]) * dot, height=len(EYE) * dot)
            for y, row in enumerate(EYE):
                for x, mark in enumerate(row):
                    if mark in colours:
                        self.eye.put(colours[mark], to=(x * dot, y * dot, (x + 1) * dot, (y + 1) * dot))
            self.eye_item = self.canvas.create_image(dot, dot * 2, anchor="nw", image=self.eye)
        if self.eye_item is not None:
            self.canvas.itemconfigure(self.eye_item, state="normal" if on else "hidden")

    def apply_capture(self) -> None:
        win32.exclude_from_capture(self.win.hwnd, bool(self.app.settings.get("hide_from_capture", True)))

    def rescale(self) -> None:
        """Nothing to rebuild at runtime: a new size applies on the next start."""

    def go_to_active(self) -> None:
        """'Come here': drop the pin and join the active window now."""
        self.pinned = False
        self.want = None
        active = win32.active_window(self.pid)
        seat = world.seat_for(active, self.monitors, self.need, self.margin)
        if seat is None:
            monitor = world.monitor_at(*win32.cursor(), self.monitors)
            seat = world.floor_seat(monitor, self.margin)
        if not self._same_place(seat):
            self._go(seat)

    def settle(self) -> None:
        """Take a seat at once, without travelling: at start and after hiding."""
        self.monitors = win32.monitors() or self.monitors
        seat = None
        if self.app.settings.get("follow_window", True):
            seat = world.seat_for(win32.active_window(self.pid), self.monitors, self.need, self.margin)
        if seat is None:
            seat = world.floor_seat(self.monitors[0], self.margin)
        self.seat = seat
        self.x = self._spot(seat)
        self.feet = seat.y
        self.mode = "rest"
        self.flight = self.fall_to = None

    def destroy(self) -> None:
        self.dead = True

    # ------------------------------------------------------------------ the loop

    def tick(self) -> None:
        if self.dead:
            return
        now = time.monotonic()
        dt = min(now - self.last, 0.1)
        self.last = now
        try:
            if not self.hidden:
                self.step(now, dt)
                self.draw(now)
        except Exception:  # one bad frame must not stop the cat
            log.exception("pet tick")
        self.app.root.after(self._interval(now), self.tick)

    def _interval(self, now: float) -> int:
        if self.hidden:
            return 400
        if self.mode in ("leap", "fall", "drag"):
            return 16
        if self.mode == "walk" or self.play_until or now - self.moved_at < 0.6:
            return 33
        if self.emote_name:
            return 60
        return 100

    def step(self, now: float, dt: float) -> None:
        through = win32.key_down(win32.VK_MENU) and self.mode != "drag"
        if through != self.through:
            self.through = through
            win32.set_click_through(self.win.hwnd, through)
        if now >= self.next_top:
            self.next_top = now + 2.0
            win32.keep_on_top(self.win.hwnd)
        if self.emote_name and now >= self.emote_until:
            self.emote_name = None
        if self.mode == "drag":
            return
        if self.mode == "tucked":
            self._stay_tucked(now)
            return
        if now >= self.next_look:
            self.next_look = now + 0.3
            self._look(now)
        if self.mode == "leap":
            self._fly(now)
        elif self.mode == "fall":
            self._drop(now, dt)
        else:
            self._ride(now)
            if self.play_until and self.mode in ("walk", "rest"):
                self._play(now, dt)
            elif self.mode == "walk":
                self._walk(dt)
            elif self.mode == "rest":
                self._idle(now)

    # ------------------------------------------------------------------ choosing a seat

    def _spot(self, seat) -> int:
        """Where on a seat the cat likes to be: where it was put by hand, else the right
        corner of a window, or a bit right of the middle of the taskbar (status bars keep
        their busy parts at the two ends)."""
        if seat.kind == "window":
            return seat.clamp(seat.right - self.rel.get(seat.hwnd, 0))
        return seat.clamp(self.floor_x.get(seat.y, seat.left + (seat.right - seat.left) * 0.62))

    def _remember(self) -> None:
        seat = self.seat
        if seat is None:
            return
        if seat.kind == "window":
            if len(self.rel) > 200:
                self.rel.clear()
            self.rel[seat.hwnd] = seat.right - self.x
        else:
            self.floor_x[seat.y] = self.x

    def _same_place(self, seat) -> bool:
        mine = self.seat
        if mine is None or mine.kind != seat.kind:
            return False
        if seat.kind == "window":
            return mine.hwnd == seat.hwnd
        return mine.y == seat.y and seat.left <= mine.right and mine.left <= seat.right

    def _live(self, seat):
        """The seat as it is this instant, or None once it is gone."""
        if seat.kind == "window":
            if not win32.is_shown(seat.hwnd):
                return None
            rect = win32.frame(seat.hwnd)
            if rect is None:
                return None
            return world.window_seat(seat.hwnd, rect, self.monitors, self.need, self.margin)
        monitor = world.monitor_at((seat.left + seat.right) // 2, seat.y - 1, self.monitors)
        if monitor is None:
            return None
        return world.floor_seat(monitor, self.margin, (seat.left - self.margin, seat.right + self.margin))

    def _look(self, now: float) -> None:
        if now - self.monitors_at > 2.0:
            self.monitors = win32.monitors() or self.monitors
            self.monitors_at = now
        active = win32.active_window(self.pid)
        if self.pinned and active and active.hwnd != self.pin and not self.play_until:
            self.pinned = False
        if self.mode in ("leap", "fall") or self.pinned or self.play_until or not active:
            self.want = None
            return
        if not self.app.settings.get("follow_window", True):
            return
        want = world.seat_for(active, self.monitors, self.need, self.margin)
        if want is None:
            return
        if self._same_place(want):
            self.want = None
            if want.kind == "floor" and want != self.seat:
                # same taskbar, but the window above it is narrower: stay under that window
                self.seat = want
                if not want.left <= self.x <= want.right and self.mode == "rest":
                    self.walk_to = want.clamp(self.x)
                    self.mode = "walk"
            return
        key = (want.kind, want.hwnd, want.y if want.kind == "floor" else 0)
        if key != self.want:
            self.want = key
            self.want_since = now
        elif now - self.want_since >= SETTLE:
            self.want = None
            self._go(want)

    def _go(self, seat) -> None:
        """Travel to another seat: walk if it is close on the same line, else leap."""
        self._remember()
        tx = self._spot(seat)
        distance = abs(tx - self.x)
        if self.seat is not None and abs(seat.y - self.feet) < 2 and distance <= 170 * self.u:
            self.seat = seat
            self.walk_to = tx
            self.mode = "walk"
            return
        span = math.hypot(tx - self.x, seat.y - self.feet)
        self.flight = dict(
            x0=self.x,
            y0=self.feet,
            t0=time.monotonic(),
            duration=min(max(span / (500.0 * self.u), 0.35), 1.0),
            height=min(40 * self.u, 12 * self.u + span * 0.15),
            seat=seat,
            rel=seat.right - tx,
        )
        self.facing = 1 if tx >= self.x else -1
        self.mode = "leap"

    # ------------------------------------------------------------------ moving

    def _ride(self, now: float) -> None:
        """Stay on the seat while its window is moved or resized."""
        seat = self.seat
        live = self._live(seat) if seat is not None else None
        if live is None:
            self._fall_to_floor(now)
            return
        if live != seat:
            keep = seat.right - self.x
            self.seat = live
            self.x = live.clamp(live.right - keep)
            self.feet = live.y
            if self.mode == "walk":
                self.walk_to = live.clamp(self.walk_to + (live.right - seat.right))
            self.moved_at = now

    def _fall_to_floor(self, now: float) -> None:
        monitor = world.monitor_at(int(self.x), int(self.feet) - 1, self.monitors)
        floor = world.floor_seat(monitor, self.margin)
        if floor.y <= self.feet + 1:
            self._land(floor, floor.clamp(self.x), now)
        else:
            self.fall_to = floor
            self.vy = 0.0
            self.mode = "fall"

    def _fly(self, now: float) -> None:
        f = self.flight
        seat = self._live(f["seat"])
        if seat is None:
            self.flight = None
            self._fall_to_floor(now)
            return
        tx, ty = seat.clamp(seat.right - f["rel"]), seat.y
        p = (now - f["t0"]) / f["duration"]
        if p >= 1.0:
            self._land(seat, tx, now)
            return
        self.x = f["x0"] + (tx - f["x0"]) * p
        self.feet = f["y0"] + (ty - f["y0"]) * p - 4 * f["height"] * p * (1 - p)
        if abs(tx - f["x0"]) > 4:
            self.facing = 1 if tx > f["x0"] else -1

    def _drop(self, now: float, dt: float) -> None:
        seat = self._live(self.fall_to) if self.fall_to is not None else None
        if seat is None:
            monitor = world.monitor_at(int(self.x), int(self.feet) - 1, self.monitors)
            seat = self.fall_to = world.floor_seat(monitor, self.margin)
        self.vy += 900.0 * self.u * dt
        self.feet += self.vy * dt
        if self.feet >= seat.y:
            self._land(seat, seat.clamp(self.x), now)

    def _land(self, seat, x: float, now: float) -> None:
        self.seat = seat
        self.x = x
        self.feet = seat.y
        self.mode = "rest"
        self.flight = self.fall_to = None
        self.vy = 0.0
        self.moved_at = now
        self._remember()

    def _walk(self, dt: float) -> None:
        gap = self.walk_to - self.x
        stride = sprites.WALK_SPEED * self.scale * dt  # as fast as the drawn legs step, so the paws do not slide
        if abs(gap) <= stride:
            self.x = self.walk_to
            self.mode = "rest"
            self._remember()
        else:
            self.facing = 1 if gap > 0 else -1
            self.x += stride * self.facing

    def _idle(self, now: float) -> None:
        if now < self.next_stroll:
            return
        self.next_stroll = now + random.uniform(70, 200)
        seat = self.seat
        if seat is None or self.emote_name or rest_anim(self.app.scene) != "sit":
            return
        reach = 60 * self.u
        lo, hi = max(seat.left, self.x - reach), min(seat.right, self.x + reach)
        if hi - lo < 16 * self.u:
            return
        target = random.uniform(lo, hi)
        if abs(target - self.x) >= 8 * self.u:
            self.walk_to = target
            self.mode = "walk"

    # ------------------------------------------------------------------ drawing

    def draw(self, now: float) -> None:
        scene = self.app.scene
        if self.mode == "drag":
            anim = "drag"
        elif self.mode == "tucked":
            anim = "sit"  # half a face looking round the edge
        elif self.mode in ("fall", "leap", "walk"):
            anim = self.mode
        elif self.emote_name:
            anim = self.emote_name
        else:
            anim = rest_anim(scene)
        if anim != self.anim:
            self.anim = anim
            self.anim_t0 = now
        look = look_of(scene)
        item = look.item if anim in ("work", "focus") else None
        rows = sprites.frame(anim, int((now - self.anim_t0) * 1000), look.acc, item, look.tie, scene.focus or 0.0, scene.mood)
        image = self.app.images.get(
            rows,
            self.app.settings.get("coat", "grey"),
            look.accent,
            bool(self.app.settings.get("outline", True)),
            anim in SIDE_ANIMS and self.facing < 0,
        )
        if image is not self.image:
            self.image = image
            self.canvas.itemconfigure(self.item, image=image)
        self.win.move(int(round(self.x - self.size / 2)), int(round(self.feet - self.size + self.sink)))

    # ------------------------------------------------------------------ mouse

    def _press(self, event) -> None:
        self.press = (event.x_root, event.y_root)
        self.dragging = False

    def _motion(self, event) -> None:
        if self.press is None:
            return
        if not self.dragging:
            if math.hypot(event.x_root - self.press[0], event.y_root - self.press[1]) < 5:
                return
            self.dragging = True
            if self.tuck is not None:  # pulled out from the edge by hand
                self.tuck = None
                self.app.on_tucked(None)
            self.mode = "drag"
            self.flight = self.fall_to = None
            self.play_until = 0.0
            self.app.on_pet_grabbed()
        # held by the scruff: the top of the head stays under the cursor
        self.x = float(event.x_root)
        self.feet = float(event.y_root + (sprites.SIZE - sprites.SCRUFF_ROW) * self.scale)
        self.draw(time.monotonic())

    def _release(self, event) -> None:
        if self.press is None:  # the second half of a double click
            return
        was_drag = self.dragging
        self.press = None
        self.dragging = False
        if not was_drag:
            self.app.on_pet_clicked()
            return
        # Let go at a side of the screen that has nothing beyond it: tuck away there.
        edge = world.outer_edge(int(self.x), int(self.feet) - self.tall // 2, self.monitors, round(14 * self.u))
        if edge is not None:
            self.app.on_tucked(self.tuck_at(edge[0], edge[1], self.feet))
            return
        seat = world.drop_seat(int(self.x), int(self.feet), win32.windows(self.pid), self.monitors, self.need, self.margin)
        active = win32.active_window(self.pid)
        self.pin = active.hwnd if active else 0
        self.pinned = True
        self.want = None
        self.x = float(seat.clamp(self.x)) if seat.kind == "floor" else self.x
        if seat.y <= self.feet:
            self._land(seat, seat.clamp(self.x), time.monotonic())
        else:
            self.fall_to = seat
            self.vy = 0.0
            self.mode = "fall"
