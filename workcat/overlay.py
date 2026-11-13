"""Borderless always-on-top windows that never take keyboard focus: the cat, its speech
bubble and its menu are all built on Overlay.

A see-through overlay is painted with one key colour wherever nothing is drawn. Windows
makes those pixels invisible and, usefully, lets clicks on them fall through to whatever
is underneath. So only the drawn pixels of the cat catch the mouse, with no polling.
"""
from __future__ import annotations

import tkinter as tk

from . import sprites, win32

KEY = "#fe00fe"
OFFSCREEN = -9000


class Overlay(tk.Toplevel):
    def __init__(self, root, width: int, height: int, see_through: bool = True):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        if see_through:
            self.configure(bg=KEY)
            self.attributes("-transparentcolor", KEY)
        self.geometry(f"{width}x{height}+{OFFSCREEN}+{OFFSCREEN}")
        self.update_idletasks()
        if not self.winfo_ismapped():
            self.update()
        self.hwnd = win32.top_level(self.winfo_id())
        win32.make_overlay(self.hwnd)
        self.pos = (OFFSCREEN, OFFSCREEN)
        self.size = (width, height)
        self.visible = True
        self.set_visible(False)

    def move(self, x: int, y: int) -> None:
        if (x, y) != self.pos:
            win32.place(self.hwnd, x, y)
            self.pos = (x, y)

    def set_box(self, width: int, height: int, x: int, y: int) -> None:
        """Size and position in one go, for windows that change size (the bubble)."""
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.size = (width, height)
        self.pos = (x, y)
        self.update_idletasks()

    def set_visible(self, visible: bool) -> None:
        if visible == self.visible:
            return
        self.visible = visible
        win32.show(self.hwnd, visible)
        if visible:
            win32.keep_on_top(self.hwnd)

    def box(self) -> tuple:
        return (self.pos[0], self.pos[1], self.pos[0] + self.size[0], self.pos[1] + self.size[1])


class Images:
    """Sprite frames turned into Tk images, built on first use and kept."""

    def __init__(self, root, scale: int):
        self.root = root
        self.scale = scale
        self.cache: dict = {}

    def get(self, rows: tuple, coat: str, accent: str = "blue", rim: bool = True, flip: bool = False, scale: int = 0, bg: str = ""):
        """`bg` is the colour behind the art: the see-through key for the cat's own
        window, or an ordinary window's background when the picture sits in a dialog."""
        scale = scale or self.scale
        key = (rows, coat, accent, rim, flip, scale, bg)
        img = self.cache.get(key)
        if img is None:
            if len(self.cache) > 500:
                self.cache.clear()
            art = sprites.mirror(rows) if flip else rows
            if rim:
                art = sprites.rimmed(art)
            pal = sprites.palette(coat, accent)
            empty = bg or KEY
            small = tk.PhotoImage(master=self.root, width=len(art[0]), height=len(art))
            small.put(" ".join("{" + " ".join(pal.get(ch, empty) for ch in row) + "}" for row in art))
            img = small.zoom(scale) if scale > 1 else small
            self.cache[key] = img
        return img
