"""How the cat's ordinary windows look: colours, type, and rounded shapes.

Tk on its own draws square grey controls. Everything rounded here (cards, buttons,
fields, tick boxes, switches, tabs) is a small picture that this file makes pixel by
pixel, at the size the screen's scaling asks for, and hands to ttk as the look of that
control. No picture files travel with the app.

The colours are the cat's own: the paper of its speech bubble, its ink, and the amber
of the bubble's main button.

    theme = use(app)        once per app; safe to call again
    Card(parent, "Title")   a white rounded box with a title
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PAGE = "#f4f1e9"  # behind the cards
CARD = "#fffefb"  # what everything sits on
LINE = "#e5dfd1"  # card edges and hairlines
INK = "#2b2e3b"
FAINT = "#7b7f8d"
GHOST = "#b3aea1"  # words on something switched off
ACCENT = "#ffcf4a"
ACCENT_HOT = "#ffdb70"
ACCENT_DOWN = "#f3c036"
ACCENT_EDGE = "#e3b024"
AMBER_INK = "#a86f00"  # amber dark enough to read as text
FIELD = "#ffffff"
FIELD_EDGE = "#d5cebf"
HOT = "#f6f2e8"  # a plain button under the mouse
DOWN = "#ece7d9"
TRACK = "#ece8dc"
SELECT = "#fff2c6"
GOOD = "#49b973"
WARN = "#f0a93b"
BAD = "#d6453d"
STRETCH = 32  # the middle of a shape's picture, in pixels: see Theme.box

# The band at the top takes a soft colour from the cat's mood.
MOOD_TINTS = {
    "content": "#fbf1d2", "happy": "#ffe8b5", "fresh": "#def3e3", "playful": "#ffe2cc", "proud": "#fce7a2", "cozy": "#f5e2ce",
    "focused": "#dae8fb", "sleepy": "#e5e0f5", "tired": "#eae5ee", "worried": "#fbdbd6", "lonely": "#dee8f2",
}


def _rgb(colour: str) -> tuple:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _name(rgb) -> str:
    return "#%02x%02x%02x" % tuple(min(255, max(0, int(round(value)))) for value in rgb)


def mix(a: str, b: str, share: float) -> str:
    """Colour `a` with `share` (0..1) of colour `b` stirred in."""
    return _name(tuple(x + (y - x) * share for x, y in zip(_rgb(a), _rgb(b))))


def _to_segment(px: float, py: float, a: tuple, b: tuple) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if not length else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Pic:
    """A small picture to draw smooth shapes on: every pixel knows how much of a shape
    covers it, so edges and corners come out soft instead of stepped."""

    def __init__(self, width: int, height: int, colour: str):
        self.w, self.h = max(1, int(width)), max(1, int(height))
        back = _rgb(colour)
        self.px = [[back] * self.w for _ in range(self.h)]

    def _lay(self, x: int, y: int, colour: tuple, cover: float) -> None:
        if cover <= 0:
            return
        cover = min(cover, 1.0)
        old = self.px[y][x]
        self.px[y][x] = (old[0] + (colour[0] - old[0]) * cover, old[1] + (colour[1] - old[1]) * cover, old[2] + (colour[2] - old[2]) * cover)

    def rounded(self, x0: float, y0: float, x1: float, y1: float, radius: float, fill: str, edge: str = "", edge_width: float = 1.0) -> "Pic":
        """A box with round corners; `radius` of half its height makes a pill or a disc."""
        inside = _rgb(fill)
        rim = _rgb(edge) if edge else None
        cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        r = max(0.0, min(radius, hw, hh))
        for y in range(max(0, int(y0) - 1), min(self.h, int(math.ceil(y1)) + 1)):
            for x in range(max(0, int(x0) - 1), min(self.w, int(math.ceil(x1)) + 1)):
                qx, qy = abs(x + 0.5 - cx) - (hw - r), abs(y + 0.5 - cy) - (hh - r)
                d = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r  # below 0: inside
                if rim is None:
                    self._lay(x, y, inside, 0.5 - d)
                else:
                    self._lay(x, y, rim, 0.5 - d)
                    self._lay(x, y, inside, 0.5 - d - edge_width)
        return self

    def stroke(self, points, width: float, colour: str) -> "Pic":
        """A line through `points`, with round ends and joints."""
        ink = _rgb(colour)
        pairs = list(zip(points, points[1:]))
        for y in range(self.h):
            for x in range(self.w):
                d = min(_to_segment(x + 0.5, y + 0.5, a, b) for a, b in pairs)
                self._lay(x, y, ink, 0.5 + width / 2 - d)
        return self

    def image(self, root) -> tk.PhotoImage:
        picture = tk.PhotoImage(master=root, width=self.w, height=self.h)
        picture.put(" ".join("{" + " ".join(_name(p) for p in row) + "}" for row in self.px))
        return picture


class Theme:
    def __init__(self, root, scale: float):
        self.root = root
        self.s = s = scale
        self.line = max(1, round(s))
        self.pad = round(16 * s)  # inside a card
        self.gap = round(12 * s)  # between cards
        self.kept: list = []  # Tk forgets a picture nobody holds on to
        self.caps: dict = {}
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._fonts()
        self._shapes()
        self._styles()

    # ------------------------------------------------------------------ type

    def _fonts(self) -> None:
        root = self.root
        for name, family, size in (("TkDefaultFont", "Segoe UI", 10), ("TkTextFont", "Segoe UI", 10), ("TkHeadingFont", "Segoe UI Semibold", 9), ("TkMenuFont", "Segoe UI", 10)):
            try:
                tkfont.nametofont(name, root=root).configure(family=family, size=size)
            except tk.TclError:
                pass
        make = lambda family, size, weight="normal": tkfont.Font(root=root, family=family, size=size, weight=weight)
        self.f_text = tkfont.nametofont("TkDefaultFont", root=root)
        self.f_column = tkfont.nametofont("TkHeadingFont", root=root)  # table headings
        self.f_small = make("Segoe UI", 9)
        self.f_bold = make("Segoe UI Semibold", 10)
        self.f_head = make("Segoe UI Semibold", 11)  # a card's title
        self.f_name = make("Segoe UI", 17, "bold")  # the cat's name
        self.f_big = make("Segoe UI Semibold", 19)  # "Ready", "Focusing: 12 min left"
        self.f_tile = make("Segoe UI Semibold", 16)  # the four numbers
        # The same in every size the numbers may shrink to, only to measure with. A font is
        # never changed just to measure: each change makes every control in every window
        # work out its size again.
        self.f_sizes = {size: make("Segoe UI Semibold", size) for size in (16, 15, 14, 13, 12, 11, 10)}
        self.f_tab = make("Segoe UI Semibold", 10)
        self.f_chat = make("Segoe UI", 10)
        self.f_chat_bold = make("Segoe UI Semibold", 10)
        self.f_title = make("Segoe UI", 15, "bold")  # the welcome window's headline

    # ------------------------------------------------------------------ shapes

    def keep(self, picture):
        self.kept.append(picture)
        return picture

    def box(self, radius: int, fill: str, edge: str, outside: str, edge_width: float = 0.0, margin: int = 0, middle: int = 0):
        """A picture of a rounded box that ttk can make any size: four corners and a
        `middle` between them. ttk does not stretch that middle, it repeats it, so it must
        not be tiny: a middle of one pixel is drawn hundreds of thousands of times to
        fill a card, and the window crawls. `margin` leaves room on the left and right."""
        size = 2 * radius + (middle or STRETCH)
        pic = Pic(size + 2 * margin, size, outside)
        pic.rounded(margin, 0, margin + size, size, radius, fill, edge, edge_width or self.line)
        return self.keep(pic.image(self.root))

    def _shapes(self) -> None:
        s, line, style, root = self.s, self.line, self.style, self.root
        have = set(style.element_names())

        def element(name: str, usual, *others, **how) -> None:
            how.setdefault("padding", 0)  # left alone, ttk keeps the words as far from the edge as the corners are wide
            if name not in have:
                style.element_create(name, "image", usual, *others, **how)

        # How small a shape may get: its corners and a pixel between them. Without this
        # ttk would let no button be lower than the picture of one, middle included.
        least = lambda r, margin=0: {"width": 2 * (r + margin) + 1, "height": 2 * r + 1}

        # a card, on the page
        r = self.r_card = round(10 * s)
        element("Card.shape", self.box(r, CARD, LINE, PAGE, middle=2 * STRETCH), border=r, sticky="nsew", **least(r))

        # buttons, on a card
        r = round(7 * s)
        plain = lambda fill, edge: self.box(r, fill, edge, CARD)
        element("Plain.button", plain(CARD, FIELD_EDGE), ("disabled", plain(CARD, LINE)), ("pressed", plain(DOWN, FIELD_EDGE)), ("active", plain(HOT, FIELD_EDGE)), border=r, sticky="nsew", **least(r))
        element("Accent.button", plain(ACCENT, ACCENT_EDGE), ("disabled", plain(mix(ACCENT, CARD, 0.6), mix(ACCENT_EDGE, CARD, 0.6))), ("pressed", plain(ACCENT_DOWN, ACCENT_EDGE)), ("active", plain(ACCENT_HOT, ACCENT_EDGE)), border=r, sticky="nsew", **least(r))
        r = round(12 * s)  # a small pill, for the questions you can ask with one click
        chip = lambda fill, edge: self.box(r, fill, edge, CARD)
        element("Chip.button", chip(HOT, LINE), ("disabled", chip(CARD, LINE)), ("pressed", chip(DOWN, FIELD_EDGE)), ("active", chip(SELECT, ACCENT_EDGE)), border=r, sticky="nsew", **least(r))

        # fields to type in, on a card
        r = round(6 * s)
        field = lambda fill, edge, width=0: self.box(r, fill, edge, CARD, width)
        states = (("disabled", field(HOT, LINE)), ("focus", field(FIELD, INK, line + 0.5)), ("active", field(FIELD, GHOST)))
        # what is inside (the words, the little arrows) keeps clear of the field's own edge
        element("Field.shape", field(FIELD, FIELD_EDGE), *states, border=r, sticky="nsew", padding=2 * line, **least(r))

        # the tabs along the top and the two-way switch: both sit on the page
        r = round(8 * s)
        gap = round(2 * s)
        tab = lambda fill, edge: self.box(r, fill, edge, PAGE, margin=gap)
        element("Tab.shape", tab(PAGE, PAGE), ("selected", tab(CARD, LINE)), ("active", tab(mix(PAGE, INK, 0.05), PAGE)), border=(r + gap, r, r + gap, r), sticky="nsew", **least(r, gap))
        seg = lambda fill, edge: self.box(r, fill, edge, CARD)  # the two-way switch sits in a card's top line
        element("Seg.shape", seg(CARD, CARD), ("selected", seg(PAGE, LINE)), ("active", seg(HOT, CARD)), border=r, sticky="nsew", **least(r))

        # tick box, round choice and switch: a picture each, with room before the words
        size = round(18 * s)
        room = round(8 * s)

        def tick(fill: str, edge: str, mark: str = "") -> tk.PhotoImage:
            pic = Pic(size + room, size, CARD).rounded(0, 0, size, size, round(5 * s), fill, edge, line)
            if mark:
                pic.stroke(((0.27 * size, 0.52 * size), (0.44 * size, 0.69 * size), (0.75 * size, 0.33 * size)), max(1.7, 0.115 * size), mark)
            return self.keep(pic.image(root))

        element(
            "Tick.box", tick(FIELD, FIELD_EDGE),
            ("disabled", "selected", tick(mix(ACCENT, CARD, 0.55), mix(ACCENT_EDGE, CARD, 0.55), GHOST)), ("disabled", tick(HOT, LINE)),
            ("selected", "active", tick(ACCENT_HOT, ACCENT_EDGE, INK)), ("selected", tick(ACCENT, ACCENT_EDGE, INK)), ("active", tick(FIELD, GHOST)),
            sticky="w",
        )

        def choice(fill: str, edge: str, dot: str = "") -> tk.PhotoImage:
            pic = Pic(size + room, size, CARD).rounded(0, 0, size, size, size / 2, fill, edge, line)
            if dot:
                third = size * 0.29
                pic.rounded(third, third, size - third, size - third, size, dot)
            return self.keep(pic.image(root))

        element(
            "Choice.dot", choice(FIELD, FIELD_EDGE),
            ("disabled", "selected", choice(mix(ACCENT, CARD, 0.55), mix(ACCENT_EDGE, CARD, 0.55), GHOST)), ("disabled", choice(HOT, LINE)),
            ("selected", "active", choice(ACCENT_HOT, ACCENT_EDGE, INK)), ("selected", choice(ACCENT, ACCENT_EDGE, INK)), ("active", choice(FIELD, GHOST)),
            sticky="w",
        )

        wide, high = round(34 * s), round(20 * s)

        def switch(track: str, edge: str, knob: str, on: bool) -> tk.PhotoImage:
            pic = Pic(wide + room + round(2 * s), high, CARD).rounded(0, 0, wide, high, high / 2, track, edge, line)
            inset = round(3 * s)
            left = wide - high + inset if on else inset
            pic.rounded(left, inset, left + high - 2 * inset, high - inset, high, knob)
            return self.keep(pic.image(root))

        element(
            "Switch.knob", switch(TRACK, FIELD_EDGE, "#ffffff", False),
            ("disabled", "selected", switch(mix(ACCENT, CARD, 0.55), mix(ACCENT_EDGE, CARD, 0.55), "#ffffff", True)), ("disabled", switch(HOT, LINE, "#ffffff", False)),
            ("selected", "active", switch(ACCENT_HOT, ACCENT_EDGE, INK, True)), ("selected", switch(ACCENT, ACCENT_EDGE, INK, True)),
            ("active", switch(DOWN, GHOST, "#ffffff", False)),
            sticky="w",
        )

        # the small arrows of lists and number fields
        def arrow(width: int, height: int, up: bool, colour: str, reach: float) -> tk.PhotoImage:
            """A small v (or its mirror), a little left of the middle: the room on its
            right keeps it clear of the field's round edge."""
            pic = Pic(width, height, FIELD)
            mid, rise = width * 0.42, reach * 0.55
            a, b = (height / 2 + rise / 2, height / 2 - rise / 2) if up else (height / 2 - rise / 2, height / 2 + rise / 2)
            pic.stroke(((mid - reach, a), (mid, b), (mid + reach, a)), max(1.3, 1.3 * s), colour)
            return self.keep(pic.image(root))

        w, h, reach = round(26 * s), round(18 * s), 4.6 * s
        element("List.downarrow", arrow(w, h, False, FAINT, reach), ("disabled", arrow(w, h, False, GHOST, reach)), ("active", arrow(w, h, False, INK, reach)), sticky="")
        w, h, reach = round(24 * s), round(11 * s), 3.6 * s
        element("Number.uparrow", arrow(w, h, True, FAINT, reach), ("pressed", arrow(w, h, True, INK, reach)), ("active", arrow(w, h, True, INK, reach)), sticky="")
        element("Number.downarrow", arrow(w, h, False, FAINT, reach), ("pressed", arrow(w, h, False, INK, reach)), ("active", arrow(w, h, False, INK, reach)), sticky="")

        # a thin scroll bar: only the part you drag
        width = round(8 * s)
        r = width // 2

        def thumb(colour: str, back: str) -> tk.PhotoImage:
            margin = round(2 * s)
            pic = Pic(width + 2 * margin, 2 * r + STRETCH, back).rounded(margin, 0, margin + width, 2 * r + STRETCH, r, colour)
            return self.keep(pic.image(root))

        for back, name in ((CARD, "Card"), (PAGE, "Page")):
            element(f"{name}.Vertical.Scrollbar.thumb", thumb("#d8d2c3", back), ("pressed", thumb(GHOST, back)), ("active", thumb("#c6bfae", back)), border=(0, r, 0, r), sticky="ns", height=2 * r + 1)

        # the bar that fills while something downloads
        high = round(8 * s)
        r = high // 2
        bar = lambda colour, back: self.keep(Pic(2 * r + STRETCH, high, back).rounded(0, 0, 2 * r + STRETCH, high, r, colour).image(root))
        element("Fill.Horizontal.Progressbar.trough", bar(TRACK, CARD), border=(r, 0, r, 0), sticky="ew", width=2 * r + 1)
        element("Fill.Horizontal.Progressbar.pbar", bar(ACCENT, TRACK), border=(r, 0, r, 0), sticky="ew", width=2 * r + 1)

    # ------------------------------------------------------------------ what each kind of control looks like

    def _styles(self) -> None:
        s, style, root = self.s, self.style, self.root
        px = lambda n: round(n * s)
        style.configure(".", background=CARD, foreground=INK, font=self.f_text, bordercolor=LINE, lightcolor=CARD, darkcolor=CARD, troughcolor=TRACK, focuscolor=CARD, selectbackground=SELECT, selectforeground=INK, insertcolor=INK)
        style.map(".", foreground=[("disabled", GHOST)])

        style.configure("TFrame", background=CARD)
        style.configure("Page.TFrame", background=PAGE)
        style.layout("Card.TFrame", [("Card.shape", {"sticky": "nsew"})])
        style.configure("Card.TFrame", background=CARD)

        style.configure("TLabel", background=CARD, foreground=INK)
        style.configure("Faint.TLabel", foreground=FAINT)
        style.configure("Small.TLabel", foreground=FAINT, font=self.f_small)
        style.configure("Head.TLabel", font=self.f_head)
        style.configure("Bold.TLabel", font=self.f_bold)
        style.configure("Big.TLabel", font=self.f_big)
        style.configure("Tile.TLabel", font=self.f_tile)
        style.configure("Title.TLabel", font=self.f_title)
        style.configure("Bad.TLabel", foreground=BAD)
        style.configure("Good.TLabel", foreground=GOOD)
        style.configure("Page.TLabel", background=PAGE)
        style.configure("PageFaint.TLabel", background=PAGE, foreground=FAINT)

        label = lambda: [("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})]
        for name, shape, pad, font in (("TButton", "Plain.button", (px(13), px(6)), self.f_text), ("Accent.TButton", "Accent.button", (px(15), px(6)), self.f_bold), ("Chip.TButton", "Chip.button", (px(11), px(3)), self.f_small)):
            style.layout(name, [(shape, {"sticky": "nswe", "children": label()})])
            style.configure(name, padding=pad, font=font, anchor="center", background=CARD, foreground=INK)
            style.map(name, foreground=[("disabled", GHOST)], background=[("active", CARD)])

        for name, shape in (("TCheckbutton", "Tick.box"), ("Switch.TCheckbutton", "Switch.knob"), ("TRadiobutton", "Choice.dot")):
            style.layout(name, [("Checkbutton.padding", {"sticky": "nswe", "children": [(shape, {"side": "left", "sticky": ""}), ("Checkbutton.label", {"side": "left", "sticky": "nswe"})]})])
            style.configure(name, padding=(0, px(3)), background=CARD, foreground=INK, wraplength=px(470))  # a long sentence beside a switch takes a second line
            style.map(name, foreground=[("disabled", GHOST)], background=[("active", CARD)])

        # the switch between today and the week: two buttons that look like one control
        style.layout("Seg.Toolbutton", [("Seg.shape", {"sticky": "nswe", "children": [("Toolbutton.padding", {"sticky": "nswe", "children": [("Toolbutton.label", {"sticky": "nswe"})]})]})])
        style.configure("Seg.Toolbutton", padding=(px(11), px(3)), font=self.f_small, background=CARD, foreground=FAINT, anchor="center")
        style.map("Seg.Toolbutton", foreground=[("selected", INK), ("active", INK)], background=[("selected", PAGE), ("active", HOT)])

        text = lambda kind: [(f"{kind}.padding", {"sticky": "nswe", "children": [(f"{kind}.textarea", {"sticky": "nswe"})]})]
        style.layout("TEntry", [("Field.shape", {"sticky": "nswe", "children": text("Entry")})])
        style.configure("TEntry", padding=(px(7), px(4)), foreground=INK, fieldbackground=FIELD, background=FIELD)
        style.layout("TCombobox", [("Field.shape", {"sticky": "nswe", "children": [("List.downarrow", {"side": "right", "sticky": ""})] + text("Combobox")})])
        style.configure("TCombobox", padding=(px(7), px(4), px(2), px(4)), foreground=INK, fieldbackground=FIELD, background=FIELD, arrowsize=px(14))
        style.map("TCombobox", foreground=[("disabled", GHOST)], fieldbackground=[("readonly", FIELD)], selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
        arrows = ("null", {"side": "right", "sticky": "", "children": [("Number.uparrow", {"side": "top", "sticky": ""}), ("Number.downarrow", {"side": "bottom", "sticky": ""})]})
        style.layout("TSpinbox", [("Field.shape", {"sticky": "nswe", "children": [arrows] + text("Spinbox")})])
        style.configure("TSpinbox", padding=(px(7), px(3), px(2), px(3)), foreground=INK, fieldbackground=FIELD, background=FIELD, arrowsize=px(11))
        for option, value in (("background", FIELD), ("foreground", INK), ("selectBackground", SELECT), ("selectForeground", INK), ("font", self.f_text), ("borderWidth", 0), ("highlightThickness", 0)):
            root.option_add("*TCombobox*Listbox." + option, value)

        style.layout("TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        style.configure("TNotebook", background=PAGE, borderwidth=0, bordercolor=PAGE, lightcolor=PAGE, darkcolor=PAGE, tabmargins=(px(10), px(8), px(10), px(4)))
        style.layout("TNotebook.Tab", [("Tab.shape", {"sticky": "nswe", "children": [("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [("Notebook.label", {"side": "top", "sticky": ""})]})]})])
        style.configure("TNotebook.Tab", padding=(px(11), px(6)), font=self.f_tab, background=PAGE, foreground=FAINT, borderwidth=0)
        style.map("TNotebook.Tab", foreground=[("selected", INK), ("active", INK)], background=[("selected", CARD), ("active", PAGE)], expand=[("selected", (0, 0, 0, 0))], padding=[("selected", (px(11), px(6)))])

        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        # the lists here are flat: no room is kept for the little arrow that opens a branch
        style.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [("Treeitem.image", {"side": "left", "sticky": ""}), ("Treeitem.text", {"side": "left", "sticky": ""})]})])
        style.configure("Treeview.Item", padding=(px(4), 0))
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK, borderwidth=0, rowheight=px(28), font=self.f_text, indent=0)
        style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", INK)])
        style.configure("Treeview.Heading", background=CARD, foreground=FAINT, font=self.f_column, relief="flat", borderwidth=0, padding=(px(4), px(5)))
        style.map("Treeview.Heading", background=[("active", CARD)], foreground=[("active", INK)])

        for name, back in (("Card", CARD), ("Page", PAGE)):
            bar = f"{name}.Vertical.TScrollbar"
            style.layout(bar, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [(f"{name}.Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            style.configure(bar, troughcolor=back, background=back, bordercolor=back, lightcolor=back, darkcolor=back, borderwidth=0, arrowsize=px(12), width=px(12))
        style.layout("Vertical.TScrollbar", style.layout("Card.Vertical.TScrollbar"))
        style.configure("Vertical.TScrollbar", troughcolor=CARD, background=CARD, bordercolor=CARD, lightcolor=CARD, darkcolor=CARD, borderwidth=0, width=px(12))

        style.layout("Horizontal.TProgressbar", [("Fill.Horizontal.Progressbar.trough", {"sticky": "ew", "children": [("Fill.Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])
        style.configure("Horizontal.TProgressbar", background=CARD, borderwidth=0, thickness=px(8))
        style.configure("TSeparator", background=LINE)

    # ------------------------------------------------------------------ drawing on a canvas

    def pill(self, canvas, x0: float, y0: float, x1: float, y1: float, colour: str, back: str, tags=()) -> None:
        """A bar with round ends, as smooth as the controls: two small pictures for the
        ends and a plain stretch between them."""
        x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
        height = y1 - y0
        if height <= 0 or x1 <= x0:
            return
        half = (height + 1) // 2
        if x1 - x0 < 2 * half:  # too short for two ends: one small blob
            key = ("blob", x1 - x0, height, colour, back)
            if key not in self.caps:
                self.caps[key] = Pic(x1 - x0, height, back).rounded(0, 0, x1 - x0, height, height, colour).image(self.root)
            canvas.create_image(x0, y0, anchor="nw", image=self.caps[key], tags=tags)
            return
        for side in ("left", "right"):
            key = (side, height, colour, back)
            if key not in self.caps:
                pic = Pic(half, height, back)
                pic.rounded(0 if side == "left" else -half, 0, 2 * half if side == "left" else half, height, height, colour)
                self.caps[key] = pic.image(self.root)
        canvas.create_image(x0, y0, anchor="nw", image=self.caps[("left", height, colour, back)], tags=tags)
        canvas.create_image(x1 - half, y0, anchor="nw", image=self.caps[("right", height, colour, back)], tags=tags)
        if x1 - x0 > 2 * half:
            canvas.create_rectangle(x0 + half, y0, x1 - half, y1, fill=colour, outline="", tags=tags)


def use(app) -> Theme:
    """The app's theme, made the first time one of its ordinary windows opens."""
    theme = getattr(app, "theme", None)
    if theme is None:
        theme = app.theme = Theme(app.root, app.ui_scale)
    return theme


class Card(ttk.Frame):
    """A white rounded box on the page, with an optional title. Its `text` is the title,
    so it can be read and changed like the titled boxes Tk has itself."""

    def __init__(self, parent, theme: Theme, title: str = "", pad=None):
        pad = theme.pad if pad is None else pad
        super().__init__(parent, style="Card.TFrame", padding=pad)
        self.title = self.head = None
        if title:
            self.head = ttk.Frame(self)  # the title's line: something small may be put at its right end
            self.head.pack(fill="x", pady=(0, round(8 * theme.s)))
            self.title = ttk.Label(self.head, text=title, style="Head.TLabel")
            self.title.pack(side="left")

    def configure(self, cnf=None, **kw):
        if cnf is None and not kw:
            return super().configure()
        options = dict(cnf or {}, **kw)
        if "text" in options:
            text = options.pop("text")
            if self.title is not None:
                self.title.configure(text=text)
        return super().configure(**options) if options else None

    config = configure

    def cget(self, key):
        if key == "text":
            return self.title.cget("text") if self.title is not None else ""
        return super().cget(key)
