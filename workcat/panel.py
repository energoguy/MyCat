"""The cat's window: today in numbers, chat, tasks, what it learned, settings.
Also the small question box and the first-run welcome.

Unlike the cat itself, these are ordinary windows: they take focus, because you type in
them. How they look (paper, white cards, the cat's amber) comes from theme.py.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import APP_NAME, __version__, apps, brain, cloud, hotkeys, i18n, llm, mood, reader, sprites, tasks, theme, weather, win32, world
from .i18n import N_, T, duration
from .store import EVERY_DAY, SCRIPTS_MOST, WORKDAYS
from .theme import AMBER_INK, BAD, CARD, FAINT, GOOD, INK, PAGE, TRACK, WARN, Card
from .tracker import slot_label

CATEGORY_COLOURS = {
    "code": "#5ed184", "office": "#4fb3ff", "design": "#ffa94d", "study": "#b48cff", "comms": "#ff8fab", "ai": "#59c9c1",
    "browser": "#aab3c2", "media": "#d59bff", "social": "#ffb3a7", "game": "#ff6b6b", "other": "#c3c8d2", "system": "#d9d9d9",
    "week": "#5ed184",  # the bars of the weekly view: a day each
}
COAT_LABELS = {"grey": N_("Grey tabby"), "ginger": N_("Ginger tabby"), "black": N_("Tuxedo"), "white": N_("White"), "cream": N_("Siamese")}
SIZES = ((0, N_("Automatic")), (1, N_("Small")), (2, N_("Medium")), (3, N_("Large")))
CHATTER = (("off", N_("Never")), ("rare", N_("Rarely")), ("normal", N_("Now and then")))
NUDGE_GOALS = (("off", N_("Never")), ("sometimes", N_("Now and then")), ("often", N_("Often")))
READ_KINDS = ("comms", "social", "office", "browser")  # kinds of program worth offering for reading
# Questions for one click in Chat: three at a time, those that fit the time of day.
QUICK = {
    "morning": (N_("Plan my day"), N_("What is on my list?"), N_("How are my goals going?")),
    "day": (N_("What should I do now?"), N_("What is on my list?"), N_("How are my goals going?")),
    "evening": (N_("What did I do today?"), N_("What should I do now?"), N_("How are my goals going?")),
}


def part_of_day(hour: int) -> str:
    return "morning" if hour < 12 else "day" if hour < 17 else "evening"
STYLES = (("playful", N_("Playful, like a cat")), ("friendly", N_("Friendly")), ("plain", N_("Straight to the point")))
LENGTHS = (("short", N_("Short")), ("normal", N_("Normal")), ("detailed", N_("Detailed")))
MODEL_WORDS = {"small": N_("small model"), "standard": N_("standard model"), "better": N_("better model")}
# Daily scripts to start from: (name, minutes after midnight, days, what to do).
SCRIPT_EXAMPLES = (
    (N_("Morning briefing"), 9 * 60, WORKDAYS, N_("Look at my open tasks, my goals and my usual hours. Tell me the three most important things for today, in order.")),
    (N_("Evening review"), 18 * 60, WORKDAYS, N_("Tell me what I finished today and what is left. Name one thing to start with tomorrow.")),
    (N_("Weekly review"), 17 * 60, 1 << 4, N_("Compare this week with last week: time at the computer, focus rounds, tasks finished. Tell me what went well and one thing to change.")),
)


def _area(app):
    """The part of the screen the cat is on that windows may use."""
    left, top, right, _bottom = app.pet.box()
    monitor = world.monitor_at((left + right) // 2, top, app.pet.monitors)
    return monitor.work if monitor else win32.Rect(0, 0, 1920, 1080)


def _place_window(win, app, width: int, height: int) -> None:
    """Put a window near the cat, fully on that monitor."""
    left, top, right, _bottom = app.pet.box()
    area = _area(app)
    x = min(max((left + right) // 2 - width // 2, area.left + 12), area.right - width - 12)
    y = top - height - 50 if top - height - 50 >= area.top + 12 else area.top + (area.height - height) // 2
    win.geometry(f"+{x}+{max(y, area.top + 12)}")


def setup_words(ai) -> str:
    """Where the one-time setup of the offline AI stands, in a sentence."""
    return ai.progress_words()


class TextValue:
    """What a box of several lines holds, read and set the way a one-line field's is."""

    def __init__(self, box: tk.Text):
        self.box = box

    def get(self) -> str:
        return self.box.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.box.delete("1.0", "end")
        if value:
            self.box.insert("1.0", value)


class Scrollable(ttk.Frame):
    """A frame whose `body` scrolls vertically. It lies on the page, between the cards."""

    def __init__(self, parent):
        super().__init__(parent, style="Page.TFrame")
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=PAGE)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Page.Vertical.TScrollbar")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(1, minsize=bar.winfo_reqwidth())  # its place is kept when it is not shown, so nothing shifts

        def moved(first, last) -> None:  # the scroll bar is there only while there is something to scroll
            if float(first) <= 0.0 and float(last) >= 1.0:
                bar.grid_remove()
            else:
                bar.grid()
            bar.set(first, last)

        self.canvas.configure(yscrollcommand=moved)
        self.body = ttk.Frame(self.canvas, style="Page.TFrame")
        inner = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(inner, width=e.width))
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.bind("<Destroy>", lambda e: self.canvas.unbind_all("<MouseWheel>") if e.widget is self else None)

    def _wheel(self, event) -> None:
        try:
            first, last = self.canvas.yview()
        except tk.TclError:  # this window is gone (seen on 2026-11-13, after the language was changed): let go of the wheel
            event.widget.unbind_all("<MouseWheel>")
            return
        if first > 0.0 or last < 1.0:  # nothing to scroll: stay put
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class Panel:
    def __init__(self, app):
        self.app = app
        s = self.s = app.ui_scale
        t = self.theme = theme.use(app)
        self.style = t.style
        win = self.win = tk.Toplevel(app.root)
        win.withdraw()
        win.title(APP_NAME)
        win.configure(bg=PAGE)
        area = _area(app)
        self.limit = round(820 * s)  # wider than this and a maximised window would only stretch things flat
        self.page_pad = round(14 * s)
        # A comfortable size where the screen has room; on a small or strongly enlarged
        # screen as much as fits, with the title bar and a little air around it.
        self.start_size = (min(round(690 * s), area.width - 24), min(round(730 * s), area.height - round(44 * s)))
        win.geometry(f"{self.start_size[0]}x{self.start_size[1]}")
        win.minsize(min(round(610 * s), self.start_size[0]), min(round(520 * s), self.start_size[1]))
        win.protocol("WM_DELETE_WINDOW", self.hide)
        self.bg = CARD  # what the drawings on cards have behind them
        self.spare = round(10 * s)  # kept free at the end of a line: a long word must not touch the card's edge
        self.wrap = self.start_size[0] - 2 * self.page_pad - 2 * t.pad - self.spare  # how wide a line of text inside a card may be
        self.flowing: list = []  # (label, how much narrower than a card's text it must stay)
        self.fitted = None
        self.f_big, self.f_head, self.f_tile = t.f_big, t.f_head, t.f_tile
        self.f_text, self.f_small, self.f_chat, self.f_chat_bold = t.f_text, t.f_small, t.f_chat, t.f_chat_bold
        self.f_heading, self.f_cell = t.f_column, t.f_text  # what tables are drawn in

        # The band at the top: the cat, how it feels and why. Its colour follows the mood.
        self.tint = theme.MOOD_TINTS["content"]
        hero = self.hero = tk.Frame(win, bg=self.tint)
        hero.pack(fill="x")
        inner = self.hero_inner = tk.Frame(hero, bg=self.tint)
        inner.pack(fill="x", padx=self.page_pad + round(4 * s), pady=round(12 * s))
        self.face = tk.Label(inner, bd=0, bg=self.tint)
        self.face.pack(side="left", padx=(0, round(14 * s)))
        side = self.hero_side = tk.Frame(inner, bg=self.tint)
        side.pack(side="right", padx=(round(12 * s), 0))
        self.energy_caption = tk.Label(side, text=T("Energy"), font=t.f_small, bg=self.tint)
        self.energy_caption.pack(anchor="e")
        self.energy_bar = tk.Canvas(side, width=round(120 * s), height=round(10 * s), highlightthickness=0, bd=0, bg=self.tint)
        self.energy_bar.pack(anchor="e", pady=round(4 * s))
        self.state_label = tk.Label(side, font=t.f_small, bg=self.tint, justify="right")
        self.state_label.pack(anchor="e")
        words = tk.Frame(inner, bg=self.tint)
        words.pack(side="left", fill="x", expand=True)
        # The cat's name, with a small pencil beside it: a click on either changes the name.
        named = tk.Frame(words, bg=self.tint)
        named.pack(anchor="w")
        self.name_label = tk.Label(named, font=t.f_name, fg=INK, bg=self.tint, anchor="w", cursor="hand2")
        self.name_label.pack(side="left")
        self.name_pencil = tk.Label(named, text="✎", font=t.f_text, bg=self.tint, cursor="hand2")
        self.name_pencil.pack(side="left", padx=(round(8 * s), 0), pady=(round(6 * s), 0))
        for part in (self.name_label, self.name_pencil):
            part.bind("<Button-1>", lambda e: self.ask_name())
        self.title_label = tk.Label(words, font=t.f_small, bg=self.tint, anchor="w")
        self.title_label.pack(anchor="w")
        self.mood_label = tk.Label(words, font=t.f_text, fg=INK, bg=self.tint, justify="left", anchor="w", wraplength=round(330 * s))
        self.mood_label.pack(anchor="w", pady=(round(4 * s), 0))

        self.book = ttk.Notebook(win)
        self.book.pack(fill="both", expand=True)
        self.pages: dict = {}
        self.today_rows: list = []
        for key, title, build in (
            ("today", T("Today"), self.build_today),
            ("chat", T("Chat"), self.build_chat),
            ("tasks", T("Tasks"), self.build_tasks),
            ("habits", T("What I learned"), self.build_habits),
            ("apps", T("Apps"), self.build_apps),
            ("brain", T("AI brain"), self.build_brain),
            ("settings", T("Settings"), self.build_settings),
        ):
            page = ttk.Frame(self.book, style="Page.TFrame", padding=(self.page_pad, round(6 * s), self.page_pad, self.page_pad))
            self.book.add(page, text=title)
            self.pages[key] = page
            build(page)
        self.book.bind("<<NotebookTabChanged>>", lambda e: self.refresh())
        win.bind("<Configure>", self.on_resize)
        self.timer = None
        app.ai.listeners.append(self.on_ai)

    # ------------------------------------------------------------------ fitting the window's width

    def flow(self, label, inset: int = 0):
        """A text that wraps where its card ends, however wide the window is made."""
        self.flowing.append((label, inset))
        label.configure(wraplength=max(round(120 * self.s), self.wrap - inset))
        return label

    def on_resize(self, event) -> None:
        if event.widget is not self.win:
            return
        content = min(event.width, self.limit)
        side = (event.width - content) // 2
        if (content, side) == self.fitted:
            return
        self.fitted = (content, side)
        self.hero_inner.pack_configure(padx=side + self.page_pad + round(4 * self.s))
        self.book.pack_configure(padx=side)
        self.wrap = max(round(200 * self.s), content - 2 * self.page_pad - 2 * self.theme.pad - self.spare)
        for label, inset in self.flowing:
            label.configure(wraplength=max(round(120 * self.s), self.wrap - inset))
        self.fit_hero()

    def fit_hero(self) -> None:
        """The sentence about the cat's mood gets the room between its face and its energy."""
        content = self.fitted[0] if self.fitted else self.start_size[0]
        taken = self.face.winfo_reqwidth() + self.hero_side.winfo_reqwidth() + 2 * self.page_pad + round(44 * self.s)
        self.mood_label.configure(wraplength=max(round(150 * self.s), content - taken))

    # ------------------------------------------------------------------ showing

    def show(self, tab: str = "today") -> None:
        """Open the window on a tab. "week" is the Today tab showing the week."""
        if tab in ("today", "week"):
            self.view.set("week" if tab == "week" else "day")
        self.book.select(self.pages.get(tab, self.pages["today"]))
        if self.win.state() == "withdrawn":
            _place_window(self.win, self.app, *self.start_size)
        if self.win.state() == "iconic":  # minimised: back up, as a click on its shortcut means
            self.win.state("normal")
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.refresh()
        self._tick()
        if tab == "chat" and self.app.ai.state == "ready":
            self.chat_entry.focus_set()

    def hide(self) -> None:
        if self.timer is not None:
            self.win.after_cancel(self.timer)
            self.timer = None
        self.win.withdraw()

    def destroy(self) -> None:
        """Take the window away for good (it is built again in another language)."""
        if self.timer is not None:
            self.win.after_cancel(self.timer)
            self.timer = None
        if self.on_ai in self.app.ai.listeners:
            self.app.ai.listeners.remove(self.on_ai)
        self.win.destroy()

    @property
    def visible(self) -> bool:
        return self.win.state() != "withdrawn"

    def _tick(self) -> None:
        if self.timer is not None:
            self.win.after_cancel(self.timer)
        self.timer = None
        if self.visible:
            self.refresh_header()
            if self.current() == "today":
                self.refresh_today()
            self.timer = self.win.after(5000, self._tick)

    def current(self) -> str:
        chosen = self.book.select()
        for key, page in self.pages.items():
            if str(page) == chosen:
                return key
        return "today"

    def refresh(self) -> None:
        if not self.visible:
            return
        self.refresh_header()
        getattr(self, "refresh_" + self.current())()

    def paint_hero(self, tint: str) -> None:
        """Give the band at the top another colour, with everything on it."""
        self.tint = tint
        soft = theme.mix(INK, tint, 0.42)  # the quieter lines: ink thinned with the band's own colour

        def visit(widget) -> None:
            widget.configure(bg=tint)
            for child in widget.winfo_children():
                visit(child)

        visit(self.hero)
        for label in (self.energy_caption, self.state_label, self.title_label, self.name_pencil):
            label.configure(fg=soft)

    def ask_name(self) -> None:
        """The name at the top of the window was clicked: ask for another one."""
        ask(self.app, T("Name"), T("What will you call me?"), lambda text, _ticked: self.app.rename_cat(text), initial=self.app.settings["name"])

    def rename_cat(self) -> None:
        """Take the name typed into Settings."""
        typed = self.cat_name.get().strip()[:20]
        if not typed:  # no name is no name: the one it has stays
            self.cat_name.set(self.app.settings["name"])
        elif typed != self.app.settings["name"]:
            self.app.rename_cat(typed)

    def refresh_header(self) -> None:
        app = self.app
        t = self.theme
        settings = app.settings
        feeling = app.condition
        tint = theme.MOOD_TINTS.get(feeling.mood, theme.MOOD_TINTS["content"])
        if tint != self.tint or not self.face.cget("image"):
            self.paint_hero(tint)
        face = app.images.get(sprites.face_rows(feeling.mood), settings["coat"], rim=False, scale=max(2, round(3 * self.s)), bg=tint)
        self.face.configure(image=face)
        self.name_label.configure(text=settings["name"])
        self.title_label.configure(text=app.job_title())
        self.mood_label.configure(text=T("{mood}. {why}", mood=T(mood.MOOD_WORDS[feeling.mood]), why=feeling.why))
        bar = self.energy_bar
        bar.delete("all")
        width, height = int(bar["width"]), int(bar["height"])
        track = theme.mix(tint, "#ffffff", 0.7)
        t.pill(bar, 0, 0, width, height, track, tint)
        colour = GOOD if feeling.energy >= 50 else WARN if feeling.energy >= 30 else "#e8695a"
        t.pill(bar, 0, 0, max(height, width * feeling.energy / 100), height, colour, track)
        hearts = "♥" * (mood.bond_level(app.bond) + 1)
        self.state_label.configure(text=T("{word}   ·   {bond} {hearts}", word=mood.energy_word(feeling.energy), bond=mood.bond_name(app.bond), hearts=hearts))
        self.fit_hero()

    # ------------------------------------------------------------------ pieces the tabs share

    def listed(self, parent, **options) -> ttk.Treeview:
        """A table in a frame of its own (`.frame`), with a scroll bar that is there
        only while there is something to scroll."""
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, **options)
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Card.Vertical.TScrollbar")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")

        def moved(first, last) -> None:
            if float(first) <= 0.0 and float(last) >= 1.0:
                bar.grid_remove()
            else:
                bar.grid(row=0, column=1, sticky="ns")
            bar.set(first, last)

        tree.configure(yscrollcommand=moved)
        tree.frame = frame
        return tree

    def fit_columns(self, tree) -> None:
        """Widen a table's narrow columns to what their title and contents need; the one
        wide column gives up the room. Titles and words differ in length by language."""
        pad = round(16 * self.s)
        names = tuple(tree["columns"])
        if not hasattr(tree, "narrowest"):
            tree.narrowest = {column: int(tree.column(column, "width")) for column in names}
        for at, column in enumerate(names):
            if self.win.tk.getboolean(tree.column(column, "stretch")):
                continue
            need = self.f_heading.measure(str(tree.heading(column, "text")))
            for item in tree.get_children():
                need = max(need, self.f_cell.measure(str(tree.item(item, "values")[at])))
            wanted = max(tree.narrowest[column], need + pad)
            if int(tree.column(column, "width")) != wanted:
                tree.column(column, width=wanted)

    # ------------------------------------------------------------------ today

    def build_today(self, page) -> None:
        s, t = self.s, self.theme
        gap = round(10 * s)
        box = Card(page, t, pad=(t.pad, round(11 * s)))
        box.pack(fill="x")
        left = ttk.Frame(box)
        left.pack(side="left")
        ttk.Label(left, text=T("Focus"), style="Small.TLabel").pack(anchor="w")
        self.focus_label = ttk.Label(left, style="Big.TLabel")
        self.focus_label.pack(anchor="w")
        self.focus_second = ttk.Button(box)
        self.focus_second.pack(side="right", padx=(round(8 * s), 0))
        self.focus_first = ttk.Button(box, style="Accent.TButton")
        self.focus_first.pack(side="right")

        tiles = self.tile_row = ttk.Frame(page, style="Page.TFrame")
        tiles.pack(fill="x", pady=(gap, 0))
        self.tiles: dict = {}
        self.tile_captions: list = []
        self.tile_pad = round(11 * s)
        self.tile_gap = round(8 * s)
        for i, (key, caption) in enumerate((("active", T("At the computer")), ("focus", T("Focus")), ("breaks", T("Breaks")), ("done", T("Tasks done")))):
            cell = Card(tiles, t, pad=self.tile_pad)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else self.tile_gap, 0))
            tiles.columnconfigure(i, weight=1, uniform="tiles")
            value = ttk.Label(cell, style="Tile.TLabel", text="0")
            value.pack(anchor="w")
            label = ttk.Label(cell, text=caption, style="Small.TLabel", justify="left")
            label.pack(anchor="w")
            self.tiles[key] = value
            self.tile_captions.append(label)
        tiles.bind("<Configure>", lambda e: self.fit_tiles())

        # The box at the bottom is put in place before the chart, so that on a small
        # screen it is the chart that gives up room, not the goals and their buttons.
        nxt = self.next_box = Card(page, t, T("Next up"), pad=(t.pad, round(12 * s)))
        nxt.pack(side="bottom", fill="x", pady=(gap, 0))
        chart = self.chart_box = Card(page, t, T("Where the time went today"), pad=(t.pad, round(12 * s)))
        chart.pack(side="top", fill="both", expand=True, pady=(gap, 0))
        self.view = tk.StringVar(value="day")  # the numbers of today, or of this week
        for value, text in (("week", T("This week")), ("day", T("Today"))):
            ttk.Radiobutton(chart.head, text=text, value=value, variable=self.view, style="Seg.Toolbutton", command=self.refresh_today).pack(side="right", padx=(round(2 * s), 0))
        self.row_h = round(25 * s)
        self.bars = tk.Canvas(chart, highlightthickness=0, bd=0, bg=CARD, height=6 * self.row_h)
        self.bars.pack(fill="both", expand=True)
        self.bars.bind("<Configure>", lambda e: self.draw_bars())

        side = self.next_side = ttk.Frame(nxt)
        ttk.Button(side, text=T("What should I do now?"), command=self.app.what_now).pack(fill="x")
        ttk.Button(side, text=T("Goals for today..."), command=self.app.ask_goals).pack(fill="x", pady=(round(6 * s), 0))
        ttk.Button(side, text=T("Habits and goals"), command=self.app.open_goals).pack(fill="x", pady=(round(6 * s), 0))
        self.goal_rows = ttk.Frame(nxt)  # one tick box for each of today's goals
        self.goals_shown = None
        self.next_label = ttk.Label(nxt, justify="left")
        self.next_for = None  # "day" or "week": what the box is laid out for

    def lay_out_next(self, week: bool) -> None:
        """The box at the bottom: today it holds the goals, what is next and two buttons;
        for the week only a line that compares it with the week before."""
        if self.next_for == ("week" if week else "day"):
            return
        self.next_for = "week" if week else "day"
        for part in (self.next_side, self.goal_rows, self.next_label):
            part.pack_forget()
        if not week:
            self.next_side.pack(side="right", anchor="n", padx=(round(10 * self.s), 0))
            self.goal_rows.pack(side="top", anchor="w")
        self.flowing = [(label, inset) for label, inset in self.flowing if label is not self.next_label]
        self.flow(self.next_label, 0 if week else self.next_side.winfo_reqwidth() + round(14 * self.s))
        self.next_label.pack(side="top", anchor="w")

    def refresh_today(self) -> None:
        app = self.app
        now = time.time()
        if app.focus.focusing:
            self.focus_label.configure(text=T("Focusing: {n} min left", n=app.focus.minutes_left(now)))
            self.focus_first.configure(text=T("Stop"), command=app.stop_focus, style="TButton")
            self.focus_second.pack_forget()
        elif app.focus.on_break:
            self.focus_label.configure(text=T("Break: {n} min left", n=app.focus.minutes_left(now)))
            self.focus_first.configure(text=T("End break"), command=app.end_break, style="TButton")
            self.focus_second.pack_forget()
        else:
            self.focus_label.configure(text=T("Ready"))
            self.focus_second.configure(text=T("Break"), command=app.start_break)
            self.focus_second.pack(side="right", padx=(round(8 * self.s), 0), before=self.focus_first)
            self.focus_first.configure(text=T("Start focus ({n} min)", n=app.settings["focus_min"]), command=app.start_focus, style="Accent.TButton")
        week = self.view.get() == "week"
        day = app.week() if week else app.summary(app.today)
        self.tiles["active"].configure(text=duration(day["active"]) if day["active"] >= 60 else "0")
        self.tiles["focus"].configure(text=T("{n} x, {m} min", n=day["focus_count"], m=day["focus_min"]) if day["focus_count"] else "0")
        self.tiles["breaks"].configure(text=str(day["breaks"]))
        self.tiles["done"].configure(text=str(day["done"]))
        self.fit_tiles()
        if week:
            self.chart_box.configure(text=T("Hours each day this week"))
            self.today_rows = [(T(tasks.WEEKDAYS[i]), seconds, "week") for i, seconds in enumerate(day["per_day"])]
        else:
            self.chart_box.configure(text=T("Where the time went today"))
            self.today_rows = day["places"][:6]
        self.draw_bars()

        self.lay_out_next(week)
        goals = app.goals_today()
        shown = tuple((goal["id"], bool(goal["done"]), goal["text"]) for goal in goals)
        if shown != self.goals_shown:  # built again only when they changed, so a tick box is not lost under the mouse
            self.goals_shown = shown
            for child in self.goal_rows.winfo_children():
                child.destroy()
            for goal in goals:
                ticked = tk.BooleanVar(value=bool(goal["done"]))
                ttk.Checkbutton(self.goal_rows, text=goal["text"] if len(goal["text"]) <= 44 else goal["text"][:43] + "…", variable=ticked, command=lambda g=goal, v=ticked: self.tick_goal(g["id"], v.get())).pack(anchor="w")
        if week:
            last = app.week(1)
            self.next_box.configure(text=T("Compared with last week"))
            self.next_label.configure(text=T("Last week: {time} at the computer. Focus rounds: {f}. Tasks done: {t}.", time=duration(last["active"]), f=last["focus_count"], t=last["done"]))
            return
        self.next_box.configure(text=T("Goals for today") if goals else T("Next up"))
        waiting = [t for t in app.store.tasks() if not t["place"] and t.get("goal") != app.today][:3]
        if waiting:
            clock = dt.datetime.now()
            rows = []
            for task in waiting:
                when = tasks.due_label(task["due"], clock)
                rows.append("• " + task["text"] + (f"  ({when})" if when else ""))
            self.next_label.configure(text="\n".join(rows))
        else:
            self.next_label.configure(text="" if goals else T("Nothing waiting."))

    def tick_goal(self, task_id: int, done: bool) -> None:
        if done:
            self.app.complete_task(task_id)
        else:
            self.app.store.update_task(task_id, done=None)
            self.app.summary_cache = (0.0, "", None)
            self.refresh_today()

    def fit_tiles(self) -> None:
        """Make the four numbers and their captions fit their tiles. Words are longer in
        some languages and a long day is a long number, so the numbers shrink a little
        and the captions wrap rather than lose their ends."""
        width = self.tile_row.winfo_width()
        if width < 100:  # not laid out yet
            return
        count = len(self.tiles)
        room = (width - (count - 1) * self.tile_gap) // count - 2 * self.tile_pad - round(8 * self.s)
        texts = [str(value.cget("text")) for value in self.tiles.values()]
        sizes = self.theme.f_sizes  # one font for each size, made once: see there why
        size = next((size for size in sizes if max(sizes[size].measure(text) for text in texts) <= room), min(sizes))
        if int(self.f_tile.cget("size")) != size:
            self.f_tile.configure(size=size)
        for caption in self.tile_captions:
            if int(str(caption.cget("wraplength")) or 0) != room:
                caption.configure(wraplength=room)

    def draw_bars(self) -> None:
        c = self.bars
        c.delete("all")
        s, t = self.s, self.theme
        width = c.winfo_width()
        if width < 50:
            return
        if not self.today_rows:
            text = T("Nothing yet. I count the time you actually spend in each program, not what you type.")
            if not self.app.may("learn_routine"):
                text = T("Learning your routine is turned off in Settings.")
            c.create_text(0, round(6 * s), anchor="nw", text=text, fill=FAINT, font=self.f_text, width=width - round(8 * s))
            return
        high = round(10 * s)
        least = round(17 * s)
        rows = self.today_rows
        if len(rows) * least > c.winfo_height() and self.view.get() == "day":
            rows = rows[:max(1, c.winfo_height() // least)]  # a very low window: the places most time went to, whole, rather than all of them cut
        row_h = max(least, min(self.row_h, c.winfo_height() // len(rows)))  # closer together when the window is short
        shown = [name if len(name) <= 22 else name[:21] + "…" for name, _, _ in rows]
        name_w = min(round(170 * s), max(self.f_text.measure(name) for name in shown) + round(16 * s))
        times = [duration(seconds) if seconds else "" for _, seconds, _ in rows]  # a day with nothing on it says nothing
        time_w = max(round(70 * s), max(self.f_small.measure(text) for text in times) + round(14 * s))  # "under a minute" is long in some languages
        most = max(seconds for _, seconds, _ in rows) or 1
        x0, x1 = name_w, width - time_w
        for i, (_name, seconds, category) in enumerate(rows):
            mid = i * row_h + row_h // 2
            top = mid - high // 2
            c.create_text(0, mid, anchor="w", text=shown[i], fill=INK, font=self.f_text)
            t.pill(c, x0, top, x1, top + high, TRACK, CARD)
            if seconds:  # a day that has not come yet has no bar at all
                t.pill(c, x0, top, x0 + max(high, (x1 - x0) * seconds / most), top + high, CATEGORY_COLOURS.get(category, "#c3c8d2"), TRACK)
            c.create_text(width, mid, anchor="e", text=times[i], fill=FAINT, font=self.f_small)

    # ------------------------------------------------------------------ chat with the AI

    def build_chat(self, page) -> None:
        s, t = self.s, self.theme
        ai = self.app.ai
        card = self.chat_setup = Card(page, t, T("My offline AI brain"))
        self.flow(ttk.Label(card, justify="left", text=T(
            "I can have a real language AI that runs only on this computer. Then you can talk to me in your own language, "
            "ask what to do next, set reminders by just saying so, and get music and film ideas.\n\n"
            "Nothing you write to me leaves this PC. The internet is used once, to download it."
        ))).pack(anchor="w", pady=(0, round(10 * s)))
        self.ai_size = tk.StringVar(value=self.app.settings["ai_model"])
        memory = win32.total_memory()
        for key, label in (("standard", T("Standard: {size}, for computers with 8 GB of memory or more")), ("small", T("Small: {size}, for older computers; simple answers in English and Russian, not for Uzbek"))):
            ttk.Radiobutton(card, text=label.format(size=llm.gb(llm.MODELS[key].size)), value=key, variable=self.ai_size, command=lambda: self.change("ai_model", self.ai_size.get())).pack(anchor="w")
        if memory:
            ttk.Label(card, text=T("This computer has {n} GB of memory.", n=round(memory / llm.GIB)), style="Small.TLabel").pack(anchor="w", padx=(round(26 * s), 0))
        self.ai_note = self.flow(ttk.Label(card, justify="left"))
        self.ai_note.pack(anchor="w", pady=(round(12 * s), round(4 * s)))
        self.ai_bar = ttk.Progressbar(card, maximum=1000, length=round(380 * s))
        self.ai_status = self.flow(ttk.Label(card, style="Faint.TLabel", justify="left"))
        self.ai_button = ttk.Button(card, command=self.ai_action, style="Accent.TButton")
        self.ai_button.pack(anchor="w", pady=(round(8 * s), 0))
        row = ttk.Frame(card)
        row.pack(fill="x", pady=(round(14 * s), 0))
        ttk.Button(row, text=T("AI brain"), command=lambda: self.show("brain")).pack(side="right", padx=(round(8 * s), 0))
        self.flow(ttk.Label(row, style="Small.TLabel", justify="left", text=T("Or use an online AI with your own key, or a bigger model: see the AI brain tab.")), round(110 * s)).pack(side="left")

        key = self.chat_key = Card(page, t, T("The online AI needs your key"))  # shown when the online AI is chosen but has no key yet
        self.flow(ttk.Label(key, justify="left", text=T("You chose an online service as my AI brain. Give me its key in the AI brain tab, and we can talk."))).pack(anchor="w", pady=(0, round(10 * s)))
        ttk.Button(key, text=T("AI brain"), command=lambda: self.show("brain"), style="Accent.TButton").pack(anchor="w")

        main = self.chat_main = Card(page, t)
        self.chat_hint = self.flow(ttk.Label(main, style="Small.TLabel", justify="left"))
        self.chat_hint.pack(side="bottom", anchor="w", pady=(round(6 * s), 0))
        row = ttk.Frame(main)
        row.pack(side="bottom", fill="x")
        self.chat_send = ttk.Button(row, text=T("Send"), command=self.send_chat, style="Accent.TButton")
        self.chat_send.pack(side="right", anchor="s", padx=(round(8 * s), 0))
        # above the field: speak instead of typing, and a window to read along with the question
        extra = ttk.Frame(main)
        extra.pack(side="bottom", fill="x", pady=(0, round(4 * s)))
        ttk.Button(extra, text=T("Speak"), style="Chip.TButton", command=self.speak).pack(side="left")
        ttk.Button(extra, text=T("Habits and goals"), style="Chip.TButton", command=self.app.open_goals).pack(side="left", padx=round(6 * s))
        self.chat_look = tk.StringVar(value=T("no window"))
        self.chat_look_field = ttk.Combobox(extra, textvariable=self.chat_look, state="readonly", width=18, postcommand=self._look_values)
        self.chat_look_field.pack(side="right")
        ttk.Label(extra, text=T("Read along:"), style="Small.TLabel").pack(side="right", padx=round(6 * s))
        # The box to write in holds several lines, for a text pasted in to be answered,
        # translated or shortened. Enter sends; Shift+Enter starts a new line.
        field = tk.Frame(row, bg=theme.FIELD_EDGE, bd=0)
        field.pack(side="left", fill="x", expand=True)
        self.chat_entry = tk.Text(
            field, height=2, wrap="word", font=self.f_chat, relief="flat", borderwidth=0, highlightthickness=0, undo=True,
            bg=theme.FIELD, fg=INK, insertbackground=INK, padx=round(8 * s), pady=round(6 * s),
        )
        self.chat_entry.pack(fill="x", padx=max(1, round(s)), pady=max(1, round(s)))
        self.chat_text = TextValue(self.chat_entry)
        self.chat_entry.bind("<Return>", self._chat_enter)
        self.chat_entry.bind("<KeyRelease>", lambda e: self._fit_entry())
        self.chat_entry.bind("<<Paste>>", lambda e: self.win.after(1, self._fit_entry))
        quick = ttk.Frame(main)
        quick.pack(side="bottom", fill="x", pady=(round(8 * s), round(8 * s)))
        self.quick_row, self.quick_for = quick, None
        self.fill_quick()
        frame = ttk.Frame(main)
        frame.pack(side="top", fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        log = self.chat_log = tk.Text(frame, wrap="word", state="disabled", relief="flat", borderwidth=0, highlightthickness=0, padx=round(2 * s), pady=round(2 * s), font=self.f_chat, bg=CARD, fg=INK, height=8, cursor="arrow", spacing2=round(2 * s))
        bar = ttk.Scrollbar(frame, orient="vertical", command=log.yview, style="Card.Vertical.TScrollbar")
        log.grid(row=0, column=0, sticky="nsew")

        def moved(first, last) -> None:
            # The scroll bar comes once the talk is longer than the window, and stays: taking
            # it away again would widen the lines, which can make the talk fit, and so on.
            if float(first) > 0.0 or float(last) < 1.0:
                bar.grid(row=0, column=1, sticky="ns")
            bar.set(first, last)

        log.configure(yscrollcommand=moved)
        log.tag_configure("you", font=self.f_chat_bold, foreground=FAINT, spacing1=round(10 * s))
        log.tag_configure("cat", font=self.f_chat_bold, foreground=AMBER_INK, spacing1=round(10 * s))
        log.tag_configure("note", foreground=FAINT, lmargin1=round(14 * s), lmargin2=round(14 * s))
        log.tag_configure("error", foreground=BAD)
        self.reply_from = None
        self.chat_started = False
        self.chat_shown = None
        del ai

    def _chat_enter(self, event) -> str:
        """Enter in the Chat box sends; with Shift it starts a new line."""
        if event.state & 0x1:
            return ""
        self.send_chat()
        return "break"

    def _fit_entry(self) -> None:
        """The box to write in grows with what is in it, from two lines up to seven."""
        box = self.chat_entry
        try:
            lines = box.count("1.0", "end", "displaylines")[0]
        except (tk.TclError, TypeError):
            lines = 2
        box.configure(height=min(7, max(2, lines)))

    def clear_chat(self) -> None:
        """Empty the Chat window (the conversation was cleared)."""
        self.chat_log.configure(state="normal")
        self.chat_log.delete("1.0", "end")
        self.chat_log.configure(state="disabled")
        self.reply_from = None
        self.chat_started = False
        self.chat_shown = None
        if self.visible and self.current() == "chat":
            self.refresh_chat()

    def copy(self, text: str, button=None) -> None:
        """Put a text on the clipboard, and let the button that was pressed say so."""
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        if button is not None:
            button.configure(text=T("Copied"))
            self.win.after(1600, lambda: button.winfo_exists() and button.configure(text=T("Copy")))

    def where_words(self) -> str:
        """The line under the chat that says where what you write goes."""
        ai = self.app.ai
        if ai.both and ai.service().ready() and ai.local is not None:
            if ai.online_down():
                return T("Answered on this computer for now: the online AI cannot be reached. I try it again by myself.")
            return T("Answered online by {service} while there is a connection, on this computer when there is not.", service=T(ai.service().service.name))
        if ai.brain is not ai.engine:
            return T("Answered online by {service}. What you write here is sent there.", service=T(ai.service().service.name))
        return T("Runs on this computer only. Nothing you write here is sent anywhere.")

    def fill_quick(self) -> None:
        """The three questions for one click, as the time of day has them."""
        part = part_of_day(dt.datetime.now().hour)
        if part == self.quick_for:
            return
        self.quick_for = part
        for child in self.quick_row.winfo_children():
            child.destroy()
        for text in QUICK[part]:
            ttk.Button(self.quick_row, text=T(text), style="Chip.TButton", command=lambda q=T(text): self.send_chat(q)).pack(side="left", padx=(0, round(6 * self.s)))

    def refresh_chat(self) -> None:
        self.fill_quick()
        ai = self.app.ai
        want = "main" if ai.state == "ready" else "key" if ai.state == "nokey" else "setup"
        if want != self.chat_shown:
            self.chat_shown = want
            cards = {"main": self.chat_main, "key": self.chat_key, "setup": self.chat_setup}
            for card in cards.values():
                card.pack_forget()
            if want == "main":
                cards[want].pack(fill="both", expand=True)
            else:
                cards[want].pack(fill="x")
        if want == "key":
            return
        if want == "main":
            ai.warm()  # the model is in memory by the time something is typed
            if not ai.busy:
                self.chat_hint.configure(text=self.where_words())
            if not self.chat_started:
                self.chat_started = True
                name = self.app.settings["name"]
                # what was said before: through the ask box, or before the app was last closed
                for who, text, notes in self.app.chat_log:
                    if who == "you":
                        self._say(T("You"), text, "you")
                    elif who.startswith("script:"):
                        self._say(T('Script "{name}"', name=who[7:]), text, "you")
                    elif who == "cat":
                        self._say(name, text or T("..."), "cat")
                        for note in notes:
                            self._note(note, live=False)
                    else:
                        self._write("\n" + T("I could not answer: {error}", error=text), "error")
                self._say(name, T("Hi! Ask me anything, or tell me what to do: remind you, tick off a task, open a program, write a text."), "cat")
            return
        self.ai_size.set(self.app.settings["ai_model"] if self.app.settings["ai_model"] in ("standard", "small") else "")
        if ai.fetching:
            self.ai_note.configure(text=T("Setting up. You can close this window: I will tell you when it is ready."))
            self.ai_bar.pack(anchor="w", before=self.ai_button, pady=(round(4 * self.s), round(4 * self.s)))
            self.ai_status.pack(anchor="w", before=self.ai_button)
            self.ai_bar.configure(value=int(1000 * ai.done / max(ai.total, 1)))
            self.ai_status.configure(text=setup_words(ai))
            self.ai_button.configure(text=T("Stop"), style="TButton")
        else:
            self.ai_bar.pack_forget()
            size = ai.download_size()
            note = T("One-time download: {size}. It continues where it stopped if interrupted.", size=llm.gb(size)) if size else T("Everything is already here.")
            self.ai_note.configure(text=note)
            if ai.error:
                self.ai_status.pack(anchor="w", before=self.ai_button)
                self.ai_status.configure(text=ai.error)
            else:
                self.ai_status.pack_forget()
            self.ai_button.configure(text=T("Set up now"), style="Accent.TButton")

    def ai_action(self) -> None:
        ai = self.app.ai
        if ai.fetching:
            ai.stop_setup()
        else:
            ai.setup()
        self.refresh()

    def on_ai(self, what: str, payload) -> None:
        """Called by the AI controller whenever something changes."""
        if what == "progress":  # several times a second while something downloads: only the bar and its line move
            if self.visible and self.current() == "chat":
                self.refresh_chat()
            elif self.visible and self.current() == "brain":
                self._brain_progress()
            return
        if what == "state":
            if self.visible and self.current() in ("chat", "brain"):
                getattr(self, "refresh_" + self.current())()
            return
        if what in ("tested", "models"):
            self.online_answer(what, *payload)
            return
        if not self.chat_started:  # this window's chat has not been opened yet: it will catch up when it is
            return
        if what == "reading":
            self.chat_hint.configure(text=T("Reading {name}...", name=payload))
        elif what == "asked":  # typed here or into the ask box by the cat, or a daily script: all are one talk
            script = self.app.script_now if self.app.ask_source == "script" else None
            self._say(T("You") if script is None else T('Script "{name}"', name=script["name"]), payload, "you")
        elif what == "thinking":
            self._begin_reply()
            self.chat_send.configure(state="disabled")
            self.chat_hint.configure(text=T("Thinking..."))
        elif what == "switched":  # the online AI did not answer: the one on this computer is asked
            self.chat_hint.configure(text=T("The online AI is not answering. Asking my brain on this computer..."))
        elif what == "text":  # the reply so far, whole: it takes the place of what was shown
            self._begin_reply()
            self._unwrite()
            self._write(payload)
        elif what == "answer":
            reply, notes = payload
            self._begin_reply()
            self._unwrite()
            self._write(reply or T("..."))
            if len(reply) >= 160:  # a text worth taking elsewhere: a letter, a translation, a plan
                self._chip(T("Copy"), lambda b: self.copy(reply, b), lead="  ")
            for note in notes:
                self._note(note)
            self._done()
        elif what == "error":
            self._write(T("I could not answer: {error}", error=payload), "error")
            self._done()

    def _begin_reply(self) -> None:
        """The cat's name on a line of its own, once, before its reply is written."""
        if self.reply_from is None:
            self._say(self.app.settings["name"], "", "cat")
            self.reply_from = self.chat_log.index("end-1c")

    def _unwrite(self) -> None:
        """Take back the part of the reply written so far."""
        if self.reply_from is not None:
            self.chat_log.configure(state="normal")
            self.chat_log.delete(self.reply_from, "end-1c")
            self.chat_log.configure(state="disabled")

    def _done(self) -> None:
        self.reply_from = None
        self.chat_send.configure(state="normal")
        self.chat_hint.configure(text=self.where_words())

    def _write(self, text: str, tag: str = "") -> None:
        log = self.chat_log
        log.configure(state="normal")
        log.insert("end", text, tag)
        log.configure(state="disabled")
        log.see("end")

    def _say(self, who: str, text: str, tag: str = "cat") -> None:
        start = "" if self.chat_log.index("end-1c") == "1.0" else "\n"
        self._write(start + who + "\n", tag)
        self._write(text)

    def _chip(self, label: str, pressed, lead: str = "") -> ttk.Button:
        """A small button inside the talk. `pressed` is called with the button itself."""
        log = self.chat_log
        log.configure(state="normal")
        if lead:
            log.insert("end", lead, "note")
        button = ttk.Button(log, text=label, width=-6, style="Chip.TButton")  # at least this wide; longer words fit too
        button.configure(command=lambda: pressed(button))
        log.window_create("end", window=button)
        log.configure(state="disabled")
        log.see("end")
        return button

    def _note(self, note: dict, live: bool = True) -> None:
        """One thing the cat did, with a way to undo it; something it asks before doing,
        with a button that says yes; or links to look something up.
        `live` is False for something from a while ago: that is listed, without buttons."""
        self._write("\n" + note.get("mark", "✓") + " " + note["text"] + "  ", "note")
        if not live:
            return
        if note.get("undo"):
            def undo(button, fn=note["undo"]):
                fn()
                button.configure(text=T("Undone"), state="disabled")

            self._chip(T("Undo"), undo)
        if note.get("do"):
            def do(button, fn=note["do"]):
                button.configure(text=T("Done"), state="disabled")
                done = fn()
                if done:
                    self._note(done)

            self._chip(T("Do it"), do)
        for label, url in note.get("links", ()):
            self._chip(label if len(label) <= 44 else label[:43] + "…", lambda b, u=url: webbrowser.open(u), lead="\n      ")
        for label, fn in note.get("buttons", ()):
            self._chip(label, lambda b, f=fn: f(), lead=" ")

    def _look_values(self) -> None:
        """The programs the person lets the cat read, for "Read along" in Chat."""
        app = self.app
        names = [app.read_name(program) for program in app.settings["ai_read_programs"]] if app.settings["ai_may_read"] else []
        self.chat_look_field.configure(values=[T("no window")] + names)

    def speak(self) -> None:
        """Windows' own voice typing (Windows key + H), with the Chat field ready for it."""
        self.chat_entry.focus_force()
        self.win.after(150, win32.voice_typing)
        self.chat_hint.configure(text=T("Windows' voice typing is opening (Windows key + H): speak, and your words appear in the field. It is Windows that listens, in the languages it offers, and it may send your voice to Microsoft to recognise it."))

    def send_chat(self, text: str = "") -> None:
        text = (text or self.chat_text.get()).strip()
        if not text or self.app.ai.state != "ready" or self.app.ai.busy:
            return
        self.refresh_chat()
        self.chat_text.set("")
        self._fit_entry()
        look = 0
        chosen = self.chat_look.get()
        if chosen != T("no window"):
            program = next((p for p in self.app.settings["ai_read_programs"] if self.app.read_name(p) == chosen), "")
            look = reader.window_of(program) if program else 0
            if not look:
                self._write("\n" + T("{name} is not showing on the screen right now.", name=chosen), "error")
                return
        if not self.app.ask_ai(text, look=look):  # when it is asked, the line appears through on_ai("asked")
            self._write("\n" + T("I am not ready yet."), "error")

    # ------------------------------------------------------------------ tasks

    def build_tasks(self, page) -> None:
        s, t = self.s, self.theme
        box = Card(page, t)
        box.pack(fill="x")
        top = ttk.Frame(box)
        top.pack(fill="x")
        self.task_text = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.task_text)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.add_task())
        ttk.Button(top, text=T("Add"), command=self.add_task, style="Accent.TButton").pack(side="left", padx=(round(8 * s), 0))
        self.flow(ttk.Label(box, text=T('Add a time at the end and I will remind you: "at 15:30", "in 20 min", "tomorrow 9:00".'), style="Small.TLabel", justify="left")).pack(anchor="w", pady=(round(6 * s), 0))

        box = Card(page, t)
        box.pack(fill="both", expand=True, pady=(t.gap, 0))
        row = ttk.Frame(box)
        row.pack(side="bottom", fill="x", pady=(round(10 * s), 0))
        ttk.Button(row, text=T("Done"), command=self.task_done).pack(side="left")
        ttk.Button(row, text=T("Delete"), command=self.task_delete).pack(side="left", padx=round(8 * s))
        self.show_done = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text=T("Show finished"), variable=self.show_done, command=self.refresh_tasks).pack(side="right")
        tree = self.task_tree = self.listed(box, columns=("when", "where"), show="tree headings", selectmode="browse", height=8)
        tree.heading("#0", text=T("Task"), anchor="w")
        tree.heading("when", text=T("When"), anchor="w")
        tree.heading("where", text=T("Where"), anchor="w")
        tree.column("#0", width=round(290 * s))
        tree.column("when", width=round(110 * s), stretch=False)
        tree.column("where", width=round(110 * s), stretch=False)
        tree.frame.pack(side="top", fill="both", expand=True)
        tree.bind("<Double-1>", lambda e: self.task_done())

    def refresh_tasks(self) -> None:
        tree = self.task_tree
        tree.delete(*tree.get_children())
        known = self.app.store.places()
        clock = dt.datetime.now()
        for task in self.app.store.tasks(include_done=self.show_done.get()):
            where = ""
            if task["place"]:
                where = (known.get(task["place"]) or {}).get("name") or task["place"]
                when = T("every time") if task["repeat"] else T("next time")
            else:
                when = tasks.due_label(task["due"], clock)
            text = ("✓ " if task["done"] else "") + task["text"]
            tree.insert("", "end", iid=str(task["id"]), text=text, values=(when, where))
        self.fit_columns(tree)

    def add_task(self) -> None:
        text = self.task_text.get().strip()
        if text:
            self.task_text.set("")
            self.app.add_task_from_text(text)

    def _picked_task(self):
        picked = self.task_tree.selection()
        return int(picked[0]) if picked else None

    def task_done(self) -> None:
        task_id = self._picked_task()
        if task_id is None:
            return
        task = self.app.store.task(task_id)
        if task and task["done"]:
            self.app.store.update_task(task_id, done=None)
            self.refresh_tasks()
        else:
            self.app.complete_task(task_id)

    def task_delete(self) -> None:
        task_id = self._picked_task()
        if task_id is not None:
            self.app.store.delete_task(task_id)
            self.refresh_tasks()

    # ------------------------------------------------------------------ what it learned

    def build_habits(self, page) -> None:
        s, t = self.s, self.theme
        area = Scrollable(page)
        area.pack(fill="both", expand=True)
        body = area.body
        beside = round(22 * s)  # the scroll bar takes this much of the width
        gutter = (0, round(8 * s))

        box = Card(body, t)
        box.pack(fill="x", padx=gutter)
        self.habit_text = self.flow(ttk.Label(box, justify="left"), beside)
        self.habit_text.pack(anchor="w")
        ttk.Button(box, text=T("Forget everything I learned..."), command=self.forget).pack(anchor="e", pady=(round(10 * s), 0))

        box = Card(body, t, T("Routines I noticed"))
        box.pack(fill="x", padx=gutter, pady=(t.gap, 0))
        tree = self.routine_tree = self.listed(box, columns=("when", "what", "seen", "remind"), show="headings", selectmode="browse", height=4)
        for column, title, width in (("when", T("Around"), 70), ("what", T("You open"), 200), ("seen", T("How often"), 120), ("remind", T("Reminder"), 80)):
            tree.heading(column, text=title, anchor="w")
            tree.column(column, width=round(width * s), stretch=column == "what")
        tree.frame.pack(fill="x")
        ttk.Button(box, text=T("Turn this reminder on or off"), command=self.toggle_routine).pack(anchor="w", pady=(round(10 * s), 0))

        box = Card(body, t, T("What you listen to and watch"))
        box.pack(fill="x", padx=gutter, pady=(t.gap, 0))
        self.media_note = self.flow(ttk.Label(box, style="Faint.TLabel", justify="left"), beside)
        self.media_note.pack(anchor="w")
        tree = self.media_tree = self.listed(box, columns=("who", "when", "time"), show="headings", selectmode="none", height=5)
        for column, title, width in (("who", T("Artist or channel"), 240), ("when", T("Mostly around"), 110), ("time", T("Last 30 days"), 110)):
            tree.heading(column, text=title, anchor="w")
            tree.column(column, width=round(width * s), stretch=column == "who")
        tree.frame.pack(fill="x")

    def refresh_habits(self) -> None:
        app = self.app
        now = time.time()
        usage, days = app.history(now)
        kind = T("weekend days") if brain.is_weekend(app.today) else T("workdays")
        parts = []
        if not app.may("learn_routine"):
            parts.append(T("Learning your routine is turned off in Settings."))
        elif len(days) < 3:
            parts.append(T("I'm still getting to know your days. I need about three {kind} with you before I can spot a routine. So far: {n}.", kind=kind, n=len(days)))
        else:
            hours = brain.typical_hours(usage, days)
            if hours:
                parts.append(T("On {kind} you usually start around {a} and wrap up around {b}.", kind=kind, a=slot_label(hours[0]), b=slot_label(hours[1])))
            total = sum(brain.totals(usage, days).values())
            parts.append(T("That is about {time} a day at the computer.", time=duration(total / len(days))))
        after = app.break_after_s(now)
        if after and after < app.settings["break_after_min"] * 60:
            parts.append(T("You usually pause by yourself after about {n} minutes, so that is when I suggest a stretch.", n=int(round(after / brain.EARLY / 60))))
        self.habit_text.configure(text=" ".join(parts))

        tree = self.routine_tree
        tree.delete(*tree.get_children())
        known = app.store.places()
        if app.may("learn_routine"):
            for routine in app.routines(now):
                row = known.get(routine.place)
                if not row or tree.exists(routine.place):
                    continue
                muted = app.store.muted("routine:" + routine.place, now)
                tree.insert("", "end", iid=routine.place, values=(slot_label(routine.slot), row["name"], T("{a} of {b} days", a=routine.seen, b=routine.days), T("off") if muted else T("on")))
        self.fit_columns(tree)

        tree = self.media_tree
        tree.delete(*tree.get_children())
        self.fit_columns(tree)

        def note(text: str) -> None:  # a line above the list, there only when it has something to say
            self.media_note.configure(text=text)
            if text:
                self.media_note.pack(anchor="w", before=tree.frame)
            else:
                self.media_note.pack_forget()

        if not app.may("learn_media"):
            note(T("Turned off. Switch on \"Notice what I listen to and watch\" in Settings and I will suggest music and videos at the times you usually play them."))
            return
        plays = app.store.plays(int(now - 30 * 86400))
        note("" if plays else T("Nothing yet. Play something and I will start to notice."))
        per: dict = {}
        for play in plays:
            name = brain.who(play)
            if not name:
                continue
            entry = per.setdefault(name, {"seconds": 0, "hours": {}})
            entry["seconds"] += play["ended"] - play["started"]
            hour = dt.datetime.fromtimestamp(play["started"]).hour
            entry["hours"][hour] = entry["hours"].get(hour, 0) + 1
        for name, entry in sorted(per.items(), key=lambda item: -item[1]["seconds"])[:8]:
            hour = max(entry["hours"], key=lambda h: entry["hours"][h])
            tree.insert("", "end", values=(name, f"{hour:02d}:00", duration(entry["seconds"])))
        self.fit_columns(tree)

    def toggle_routine(self) -> None:
        picked = self.routine_tree.selection()
        if not picked:
            return
        key = "routine:" + picked[0]
        if self.app.store.muted(key):
            self.app.store.unmute(key)
        else:
            self.app.store.mute(key)
        self.refresh_habits()

    def forget(self) -> None:
        if messagebox.askyesno(APP_NAME, T("Erase everything I learned about your days, apps, music and videos, my notes about you and our conversation?\n\nYour tasks and settings stay. This cannot be undone."), parent=self.win):
            self.app.forget_everything()

    # ------------------------------------------------------------------ apps

    def build_apps(self, page) -> None:
        s, t = self.s, self.theme
        box = Card(page, t)
        box.pack(fill="both", expand=True)
        self.flow(ttk.Label(box, text=T("The programs and sites I have seen you use. If I guessed the kind of work wrong, fix it here: it changes how I dress and how the day is counted."), style="Small.TLabel", justify="left")).pack(anchor="w", pady=(0, round(8 * s)))
        row = ttk.Frame(box)
        row.pack(side="bottom", fill="x", pady=(round(10 * s), 0))
        self.kind = tk.StringVar()
        self.kind_names = {T(name): key for key, name in apps.CATEGORY_NAMES.items()}
        ttk.Combobox(row, textvariable=self.kind, state="readonly", values=list(self.kind_names), width=26).pack(side="left")
        ttk.Button(row, text=T("Set kind"), command=self.set_kind).pack(side="left", padx=round(8 * s))
        tree = self.app_tree = self.listed(box, columns=("kind", "week"), show="tree headings", selectmode="browse", height=10)
        tree.heading("#0", text=T("Program or site"), anchor="w")
        tree.heading("kind", text=T("Kind of work"), anchor="w")
        tree.heading("week", text=T("Last 7 days"), anchor="w")
        tree.column("#0", width=round(230 * s))
        tree.column("kind", width=round(170 * s), stretch=False)
        tree.column("week", width=round(110 * s), stretch=False)
        tree.frame.pack(side="top", fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", lambda e: self._show_kind())

    def refresh_apps(self) -> None:
        app = self.app
        tree = self.app_tree
        keep = tree.selection()
        tree.delete(*tree.get_children())
        first = (dt.date.fromisoformat(app.today) - dt.timedelta(days=6)).isoformat()
        week = brain.totals(app.tracker.usage(first, app.today), [(dt.date.fromisoformat(first) + dt.timedelta(days=i)).isoformat() for i in range(7)])
        rows = [row for row in app.store.places().values() if row["category"] != "system"]
        rows.sort(key=lambda row: -week.get(row["place"], 0))
        for row in rows:
            seconds = week.get(row["place"], 0)
            tree.insert("", "end", iid=row["place"], text=row["name"], values=(T(apps.CATEGORY_NAMES.get(row["category"], "Other")), duration(seconds) if seconds else ""))
        self.fit_columns(tree)
        if keep and tree.exists(keep[0]):
            tree.selection_set(keep[0])

    def _show_kind(self) -> None:
        picked = self.app_tree.selection()
        if picked:
            self.kind.set(self.app_tree.set(picked[0], "kind"))

    def set_kind(self) -> None:
        picked = self.app_tree.selection()
        category = self.kind_names.get(self.kind.get())
        if not picked or not category:
            return
        self.app.store.set_category(picked[0], category)
        self.app.tracker.categories[picked[0]] = category
        self.refresh_apps()

    # ------------------------------------------------------------------ settings

    def build_settings(self, page) -> None:
        s, t = self.s, self.theme
        settings = self.app.settings
        area = Scrollable(page)
        area.pack(fill="both", expand=True)
        body = area.body
        beside = round(22 * s)  # the scroll bar takes this much of the width
        under = round(44 * s)  # a hint starts where the words beside a switch start
        dot = round(26 * s)  # and beside a round choice, here

        def section(title: str):
            box = Card(body, t, title)
            box.pack(fill="x", pady=(0, t.gap), padx=(0, round(8 * s)))
            return box

        def check(box, key: str, text: str, hint: str = "") -> None:
            var = tk.BooleanVar(value=bool(settings[key]))
            ttk.Checkbutton(box, text=text, variable=var, style="Switch.TCheckbutton", command=lambda: self.change(key, var.get())).pack(anchor="w")
            if hint:
                self.flow(ttk.Label(box, text=hint, style="Small.TLabel", justify="left"), beside + under).pack(anchor="w", padx=(under, 0), pady=(0, round(6 * s)))

        def choice(box, key: str, text: str, options) -> None:
            row = ttk.Frame(box)
            row.pack(fill="x", pady=round(3 * s))
            ttk.Label(row, text=text).pack(side="left")
            labels = [T(label) for _, label in options]
            var = tk.StringVar(value=next((T(label) for value, label in options if value == settings[key]), labels[0]))
            combo = ttk.Combobox(row, textvariable=var, state="readonly", values=labels, width=18)
            combo.pack(side="right")
            combo.bind("<<ComboboxSelected>>", lambda e: self.change(key, options[labels.index(var.get())][0]))

        def number(box, key: str, text: str, low: int, high: int) -> None:
            row = ttk.Frame(box)
            row.pack(fill="x", pady=round(3 * s))
            self.flow(ttk.Label(row, text=text, justify="left"), beside + round(90 * s)).pack(side="left")
            var = tk.StringVar(value=str(settings[key]))

            def commit(*_):
                try:
                    value = min(max(int(var.get()), low), high)
                except ValueError:
                    value = settings[key]
                var.set(str(value))
                self.change(key, value)

            spin = ttk.Spinbox(row, from_=low, to=high, textvariable=var, width=5, command=commit)
            spin.pack(side="right")
            spin.bind("<FocusOut>", commit)
            spin.bind("<Return>", commit)

        box = section(T("Your cat"))
        choice(box, "language", T("Language"), tuple(i18n.LANGUAGES.items()))
        row = ttk.Frame(box)
        row.pack(fill="x", pady=round(3 * s))
        ttk.Label(row, text=T("Name")).pack(side="left")
        ttk.Button(row, text=T("Save"), width=-6, command=self.rename_cat).pack(side="right", padx=(round(6 * s), 0))
        called = self.cat_name = tk.StringVar(value=settings["name"])
        entry = self.name_field = ttk.Entry(row, textvariable=called, width=21)
        entry.pack(side="right")
        entry.bind("<FocusOut>", lambda e: self.rename_cat())  # leaving the field saves too, as does Enter
        entry.bind("<Return>", lambda e: self.rename_cat())
        choice(box, "coat", T("Coat"), tuple(COAT_LABELS.items()))
        choice(box, "size", T("Size (applies the next time I start)"), SIZES)
        check(box, "outline", T("Light edge, so I show up on dark windows"))

        box = section(T("How I behave"))
        check(box, "follow_window", T("Sit on the window you are working in"), T("When a window fills the screen there is no room on top, so I sit on the taskbar below it. Drag me anywhere; I stay until you switch to another window."))
        choice(box, "chatter", T("Small talk"), CHATTER)
        check(box, "hide_in_fullscreen", T("Hide while something is full screen"), T("Games, videos, presentations."))
        check(box, "quiet_in_calls", T("Stay quiet during calls"), T("I only check whether the microphone is in use. I never listen."))
        check(box, "hide_from_capture", T("Keep me out of screenshots and screen sharing"), T("Colleagues on a call will not see me or my reminders."))
        check(box, "autostart", T("Start with Windows"))

        box = section(T("Work rhythm"))
        number(box, "focus_min", T("Focus session, minutes"), 5, 180)
        number(box, "break_min", T("Break, minutes"), 1, 60)
        number(box, "break_after_min", T("Suggest a stretch after this many minutes without a pause (0 = never)"), 0, 240)
        check(box, "adaptive_breaks", T("Fit that to my own rhythm"), T("If you usually pause sooner than that, I suggest the stretch when you run past your usual time."))

        box = section(T("What I may learn (it all stays on this computer)"))
        check(box, "learn_routine", T("My routine: which programs I use and when"), T("Lets me say \"you usually open Excel around 9:30\". I store program names and minutes, never what you type or see."))
        check(box, "learn_sites", T("Well-known sites in my browser"), T("So YouTube, Gmail or GitHub count as their own places. I read the tab's title, keep only the site's name and drop the rest."))
        check(box, "learn_media", T("Notice what I listen to and watch"), T("Titles and artists from Windows' \"now playing\" info, to suggest music and videos at the times you usually play them."))

        box = section(T("Your day"))
        check(box, "goals_ask", T("Ask for my three goals each morning"))
        check(box, "recap", T("Tell me about my day when I finish"), T("Around the time you usually stop: hours, focus rounds, tasks done, what is left."))
        check(box, "week_note", T("Point me to the weekly report once a week"))
        number(box, "eye_rest_min", T("Remind me to rest my eyes after this many minutes at the screen (0 = never)"), 0, 240)
        number(box, "water_min", T("Remind me to drink water every this many minutes (0 = never)"), 0, 480)
        check(box, "sounds", T("Soft sounds: a small meow with a reminder, a purr when I pet you"))

        box = section(T("What I remind you of by myself"))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T(
            "Now and then, one thing at a time, and never during a call, a focus round or something full screen."
        )), beside).pack(anchor="w", pady=(0, round(6 * s)))
        choice(box, "nudge_goals", T("My tasks and goals, with a joke"), NUDGE_GOALS)
        check(box, "nudge_meals", T("Breakfast and lunch"))
        number(box, "breakfast_until", T("Ask about breakfast until this hour"), 5, 12)
        number(box, "lunch_hour", T("Ask about lunch from this hour"), 11, 16)
        check(box, "nudge_late", T("That it is getting late"))
        number(box, "late_hour", T("Late begins at this hour"), 18, 23)
        check(box, "nudge_days", T("What kind of day it is"), T("Well-known days of the year, and your own dates below: on the day, and the day before."))
        self.own_box = ttk.Frame(box)  # the person's own dates, one row each
        self.own_box.pack(fill="x", padx=(under, beside))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T("A date of your own, a birthday for example: its name, then the day and the month.")), beside + under).pack(anchor="w", padx=(under, 0), pady=(round(4 * s), 0))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=(under, beside), pady=(round(2 * s), round(8 * s)))
        self.own_name = tk.StringVar()
        ttk.Entry(row, textvariable=self.own_name, width=22).pack(side="left")
        self.own_day, self.own_month = tk.StringVar(value="1"), tk.StringVar(value="1")
        ttk.Spinbox(row, from_=1, to=31, textvariable=self.own_day, width=3, wrap=True).pack(side="left", padx=(round(8 * s), 0))
        ttk.Label(row, text=".").pack(side="left", padx=round(2 * s))
        ttk.Spinbox(row, from_=1, to=12, textvariable=self.own_month, width=3, wrap=True).pack(side="left")
        ttk.Button(row, text=T("Add"), width=-6, command=self.add_own_day).pack(side="left", padx=round(8 * s))
        self.fill_own_days()
        check(box, "weather", T("The weather"), T(
            "In the morning, and when rain or snow is on its way. For this I ask Open-Meteo, a free weather service: the name of your city and its place on the map go there, nothing else. It is the one thing I fetch from the internet without being asked each time."
        ))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=(under, beside), pady=round(3 * s))
        ttk.Label(row, text=T("City")).pack(side="left")
        ttk.Button(row, text=T("Save"), width=-6, command=self.save_city).pack(side="right", padx=(round(6 * s), 0))
        self.city = tk.StringVar(value=settings["weather_city"])
        field = ttk.Entry(row, textvariable=self.city, width=21)
        field.pack(side="right")
        field.bind("<Return>", lambda e: self.save_city())
        field.bind("<FocusOut>", lambda e: self.save_city())
        guess = weather.guess_city()
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=(
            T("Left empty, I take the capital of the country Windows is set to: {city}.", city=guess) if guess else T("Type your city, and I can tell you its weather.")
        )), beside + under).pack(anchor="w", padx=(under, 0), pady=(0, round(4 * s)))

        box = section(T("Shortcut keys"))
        self.flow(ttk.Label(box, text=T("They work in any program. Click a field and press the keys you want; Backspace removes a shortcut."), style="Small.TLabel", justify="left"), beside).pack(anchor="w", pady=(0, round(6 * s)))
        self.key_fields: dict = {}
        for action, label in hotkeys.NAMES.items():
            row = ttk.Frame(box)
            row.pack(fill="x", pady=round(3 * s))
            ttk.Label(row, text=T(label)).pack(side="left")
            field = ttk.Entry(row, width=21, justify="center")
            field.pack(side="right")
            field.bind("<KeyPress>", lambda e, n=action: self.key_pressed(n, e))
            field.bind("<FocusIn>", lambda e: self.app.tray.set_shortcuts({}))  # so the old key can be pressed here without doing its job
            field.bind("<FocusOut>", lambda e: self.app.tray.set_shortcuts(hotkeys.merged(self.app.settings["hotkeys"])))
            self.key_fields[action] = field
        self.key_note = self.flow(ttk.Label(box, style="Bad.TLabel", justify="left"), beside)
        self.key_note.pack(anchor="w")

        box = section(T("Your data"))
        self.flow(ttk.Label(box, text=str(self.app.store.folder), style="Small.TLabel", justify="left"), beside).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(round(8 * s), 0))
        ttk.Button(row, text=T("Open this folder"), command=lambda: os.startfile(self.app.store.folder)).pack(side="left")
        ttk.Button(row, text=T("Forget everything I learned..."), command=self.forget).pack(side="left", padx=round(8 * s))

    def refresh_settings(self) -> None:
        app = self.app
        settings = app.settings
        typing_in = self.focused()

        # the shortcut keys, and what is wrong with them if anything
        keys = hotkeys.merged(settings["hotkeys"])
        for name, field in self.key_fields.items():
            if typing_in is not field:
                self._show_key(field, keys[name])
        clashing = hotkeys.clashes(keys)
        taken = [keys[name] for name in sorted(app.tray.taken) if keys.get(name)]
        if clashing:
            self.key_note.configure(text=T("Two shortcuts use the same keys: only one of them can work."))
        elif taken:
            self.key_note.configure(text=T("Another program already uses {keys}. Pick different keys.", keys=", ".join(taken)))
        else:
            self.key_note.configure(text="")

    def focused(self):
        """The field being typed in, if any."""
        try:
            return self.win.focus_get()
        except KeyError:  # the list a field has dropped down: tkinter cannot name it
            return None

    def _show_key(self, field, keys: str) -> None:
        field.delete(0, "end")
        field.insert(0, keys or T("none"))

    def key_pressed(self, name: str, event) -> str:
        """A key was pressed in one of the shortcut fields."""
        field = self.key_fields[name]
        if event.keysym in ("BackSpace", "Delete") and not event.state & 0x20004:
            keys = ""
        elif event.keysym in ("Escape", "Tab", "Return"):
            self.win.focus_set()
            return "break"
        else:
            keys = hotkeys.pressed(event.state, event.keycode)
            if not keys:  # only Ctrl or Alt so far, or a key on its own: keep waiting
                return "break"
        self._show_key(field, keys)
        saved = dict(self.app.settings["hotkeys"])
        saved[name] = keys
        self.app.settings["hotkeys"] = saved
        self.app.store.save_settings()
        self.win.focus_set()  # done: leaving the field registers the keys again
        return "break"

    def fill_own_days(self) -> None:
        """The person's own dates in Settings: one row each, with Delete."""
        s = self.s
        for child in self.own_box.winfo_children():
            child.destroy()
        for row in self.app.store.own_days():
            line = ttk.Frame(self.own_box)
            line.pack(fill="x", pady=round(1 * s))
            ttk.Button(line, text=T("Delete"), style="Chip.TButton", command=lambda i=row["id"]: (self.app.store.delete_own_day(i), self.fill_own_days())).pack(side="right")
            ttk.Label(line, text=f"{row['day']:02d}.{row['month']:02d}   {row['name']}").pack(side="left")

    def add_own_day(self) -> None:
        name = " ".join(self.own_name.get().split())[:60]
        try:
            day, month = int(float(self.own_day.get())), int(float(self.own_month.get()))
        except ValueError:
            return
        if not name or not 1 <= month <= 12 or not 1 <= day <= (29 if month == 2 else 30 if month in (4, 6, 9, 11) else 31):
            return
        self.app.store.add_own_day(name, month, day)
        self.own_name.set("")
        self.fill_own_days()

    def save_city(self) -> None:
        self.change("weather_city", " ".join(self.city.get().split())[:60])

    # ------------------------------------------------------------------ the AI brain

    def switch(self, box, key: str, text: str, hint: str = "", inset: int = 0):
        """An on-off switch for one setting, with a small line of explanation under it."""
        s = self.s
        under = round(44 * s)  # the hint starts where the words beside the switch start
        var = tk.BooleanVar(value=bool(self.app.settings[key]))
        ttk.Checkbutton(box, text=text, variable=var, style="Switch.TCheckbutton", command=lambda: self.change(key, var.get())).pack(anchor="w")
        if hint:
            self.flow(ttk.Label(box, text=hint, style="Small.TLabel", justify="left"), inset + under).pack(anchor="w", padx=(under, 0), pady=(0, round(6 * s)))
        self.switches[key] = var
        return var

    def pick(self, box, key: str, text: str, options) -> None:
        """A row with a list to choose one setting from."""
        row = ttk.Frame(box)
        row.pack(fill="x", pady=round(3 * self.s))
        ttk.Label(row, text=text).pack(side="left")
        labels = [T(label) for _, label in options]
        var = tk.StringVar()
        combo = ttk.Combobox(row, textvariable=var, state="readonly", values=labels, width=24)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: self.change(key, options[labels.index(var.get())][0]))
        self.picks[key] = (var, options)

    def build_brain(self, page) -> None:
        s, t = self.s, self.theme
        settings = self.app.settings
        area = Scrollable(page)
        area.pack(fill="both", expand=True)
        body = area.body
        beside = round(22 * s)  # the scroll bar takes this much of the width
        dot = round(26 * s)  # what belongs to a round choice starts here
        self.switches: dict = {}
        self.picks: dict = {}

        def section(title: str):
            box = Card(body, t, title)
            box.pack(fill="x", pady=(0, t.gap), padx=(0, round(8 * s)))
            return box

        # how things stand
        box = section(T("My AI brain"))
        self.brain_status = self.flow(ttk.Label(box, style="Bold.TLabel", justify="left"), beside)
        self.brain_status.pack(anchor="w")
        self.brain_more = self.flow(ttk.Label(box, style="Small.TLabel", justify="left"), beside)
        self.brain_more.pack(anchor="w", pady=(round(2 * s), 0))
        self.brain_bar = ttk.Progressbar(box, maximum=1000, length=round(380 * s))
        self.brain_progress = self.flow(ttk.Label(box, style="Faint.TLabel", justify="left"), beside)
        row = self.brain_buttons = ttk.Frame(box)
        row.pack(fill="x", pady=(round(10 * s), 0))
        self.ai_test = ttk.Button(row, text=T("Test"), command=self.test_brain, style="Accent.TButton")
        self.ai_test.pack(side="left")
        ttk.Button(row, text=T("Open Chat"), command=lambda: self.show("chat")).pack(side="left", padx=round(8 * s))
        self.ai_result = self.flow(ttk.Label(box, justify="left"), beside)  # shown once there is something to say

        # where the thinking happens: on this computer, or online
        box = section(T("Where I think"))
        self.ai_source = tk.StringVar(value=settings["ai_source"])
        pick_source = lambda: self.change("ai_source", self.ai_source.get())
        for value, label in (
            ("offline", T("On this computer: private, free, works without the internet")),
            ("online", T("Online, with my own key: a big model on the internet answers")),
            ("both", T("Both: online while there is a connection, this computer when there is not")),
        ):
            ttk.Radiobutton(box, text=label, value=value, variable=self.ai_source, command=pick_source).pack(anchor="w")
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T(
            "With \"Both\" I switch by myself: when the online AI cannot be reached, the one on this computer answers within a couple of seconds, and I go back online when the connection is there again."
        )), beside + dot).pack(anchor="w", padx=(dot, 0), pady=(0, round(10 * s)))
        ttk.Label(box, text=T("The AI on this computer"), style="Head.TLabel").pack(anchor="w", pady=(0, round(2 * s)))
        offline = ttk.Frame(box)
        offline.pack(fill="x", padx=(dot, 0), pady=(round(2 * s), round(12 * s)))
        self.brain_size = tk.StringVar(value=settings["ai_model"])
        for key, label in (
            ("small", T("Small: {size}, for older computers; simple answers in English and Russian, not for Uzbek")),
            ("standard", T("Standard: {size}, for computers with 8 GB of memory or more")),
            ("better", T("Better: {size}, clearly smarter, also in Uzbek; slower, needs 16 GB of memory")),
        ):
            ttk.Radiobutton(offline, text=label.format(size=llm.gb(llm.MODELS[key].size)), value=key, variable=self.brain_size, command=lambda: self.change("ai_model", self.brain_size.get())).pack(anchor="w")
        memory = win32.total_memory()
        if memory:
            ttk.Label(offline, text=T("This computer has {n} GB of memory.", n=round(memory / llm.GIB)), style="Small.TLabel").pack(anchor="w", padx=(dot, 0))
        self.brain_line = self.flow(ttk.Label(offline, style="Small.TLabel", justify="left"), beside + dot)
        self.brain_line.pack(anchor="w", pady=(round(8 * s), 0))
        row = ttk.Frame(offline)
        row.pack(fill="x", pady=(round(6 * s), round(6 * s)))
        self.brain_fetch = ttk.Button(row, command=self.ai_action)
        self.brain_fetch.pack(side="left")
        self.ai_remove = ttk.Button(row, text=T("Remove it from this computer..."), command=self.remove_ai)
        self.ai_remove.pack(side="left", padx=round(8 * s))
        self.switch(offline, "ai_keep_ready", T("Keep it ready all the time"), T(
            "Then the first answer comes sooner, and the model stays in the computer's memory for as long as I run. Without this it leaves the memory half an hour after your last question."
        ), beside + dot)

        ttk.Label(box, text=T("The online AI"), style="Head.TLabel").pack(anchor="w", pady=(0, round(2 * s)))
        online = ttk.Frame(box)
        online.pack(fill="x", padx=(dot, 0), pady=(round(2 * s), 0))
        self.flow(ttk.Label(online, style="Small.TLabel", justify="left", text=T(
            "Then what you write to me, my notes about your day and what I know about you are sent to that service. The key comes from the service's own website, and the service charges you for what you use."
        )), beside + dot).pack(anchor="w", pady=(0, round(6 * s)))

        def line(text: str):
            row = ttk.Frame(online)
            row.pack(fill="x", pady=round(3 * s))
            ttk.Label(row, text=text).pack(side="left")
            return row

        self.service_names = {T(service.name): key for key, service in cloud.SERVICES.items()}
        self.ai_service = tk.StringVar(value=T(cloud.SERVICES.get(settings["ai_service"], cloud.SERVICES["claude"]).name))
        combo = ttk.Combobox(line(T("Service")), textvariable=self.ai_service, state="readonly", values=list(self.service_names), width=30)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: self.pick_service())
        row = line(T("Key"))
        ttk.Button(row, text=T("Save"), width=-6, command=self.save_key).pack(side="right", padx=(round(6 * s), 0))
        self.ai_key = tk.StringVar()
        entry = self.ai_key_field = ttk.Entry(row, textvariable=self.ai_key, show="•", width=24)
        entry.pack(side="right")
        entry.bind("<Return>", lambda e: self.save_key())
        self.ai_key_note = self.flow(ttk.Label(online, style="Small.TLabel", justify="left"), beside + dot)
        self.ai_key_note.pack(anchor="w")
        row = self.ai_model_row = line(T("Model"))
        ttk.Button(row, text=T("Get the list"), command=self.fetch_models).pack(side="right", padx=(round(6 * s), 0))
        self.ai_model_name = tk.StringVar()
        self.ai_models = ttk.Combobox(row, textvariable=self.ai_model_name, width=30, postcommand=self.models_opened)
        self.ai_models.pack(side="right")
        self.models_of = None  # the service and the names the list holds
        for event in ("<<ComboboxSelected>>", "<FocusOut>", "<Return>"):
            self.ai_models.bind(event, lambda e: self.pick_model())
        row = self.ai_address_row = line(T("Address"))  # asked for only when the service has none of its own
        self.ai_address = tk.StringVar(value=settings["ai_address"])
        entry = self.ai_address_field = ttk.Entry(row, textvariable=self.ai_address, width=34)
        entry.pack(side="right")
        for event in ("<FocusOut>", "<Return>"):
            entry.bind(event, lambda e: self.change("ai_address", self.ai_address.get().strip()))
        self.ai_online_end = ttk.Frame(online)
        self.ai_online_end.pack(fill="x", pady=(round(6 * s), 0))
        ttk.Button(self.ai_online_end, text=T("Forget the key"), command=self.forget_key).pack(anchor="w", pady=(round(6 * s), 0))
        self.flow(ttk.Label(box, style="Faint.TLabel", justify="left", text=T(
            "Private unless you choose otherwise: on this computer, nothing you write is sent anywhere. The online AI is used only if you pick it here."
        )), beside).pack(anchor="w", pady=(round(12 * s), 0))

        box = section(T("How I talk"))
        self.pick(box, "ai_style", T("Manner"), STYLES)
        self.pick(box, "ai_length", T("Length of my answers"), LENGTHS)

        box = section(T("What I may do when you ask"))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T(
            "\"I sent the report\", \"move the bank call to tomorrow at 10\", \"open Excel\": I do it, say what I did, and show Undo."
        )), beside).pack(anchor="w", pady=(0, round(6 * s)))
        self.switch(box, "ai_may_add", T("Add reminders and tasks"), "", beside)
        self.switch(box, "ai_may_edit", T("Finish, move and delete tasks, set the day's goals"), "", beside)
        self.switch(box, "ai_may_timer", T("Start the focus timer and breaks"), "", beside)
        self.switch(box, "ai_may_open", T("Open programs and sites, search the web"), T(
            "Only programs I have seen you use or that are in your Start menu, sites I know, and addresses you type yourself. A search opens in your browser. I cannot run commands."
        ), beside)
        self.switch(box, "ai_may_read", T("Read what other programs show"), T(
            "For a question that asks for it, or a daily script that says \"Look at\". Only the programs you tick here, only what their window shows at that moment, and only for that one answer: I keep none of it, and I never click or type in them. What such an answer wants done is only ever offered with a \"Do it\" button. While this is on, I wear a small eye."
        ), beside)
        self.read_box = ttk.Frame(box)  # the programs, and where their text may go: filled in while the switch is on
        self.read_box.pack(fill="x", padx=(round(44 * s), 0))
        self.read_shown = None
        self.read_vars: dict = {}
        self.read_where = tk.StringVar()
        self.read_result = None
        self.switch(box, "ai_ask_first", T("Ask me before changing or opening anything"), T("Off: I do it at once and show Undo. On: I show a \"Do it\" button and wait for you."), beside)
        self.switch(box, "plan_morning", T("Offer a plan for my day each morning"), "", beside)

        box = section(T("Daily scripts"))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T(
            "Things I do for you every day at a set time. You write what, in your own words, and I tell you what came of it."
        )), beside).pack(anchor="w", pady=(0, round(6 * s)))
        self.scripts_box = ttk.Frame(box)
        self.scripts_box.pack(fill="x")
        self.scripts_shown = None
        self.script_vars: list = []
        ttk.Button(box, text=T("Add a script..."), command=self.edit_script, style="Accent.TButton").pack(anchor="w", pady=(round(10 * s), 0))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T("Or start from one of these and change it to your liking:")), beside).pack(anchor="w", pady=(round(10 * s), round(4 * s)))
        row = ttk.Frame(box)
        row.pack(fill="x")
        for example in SCRIPT_EXAMPLES:
            ttk.Button(row, text=T(example[0]), style="Chip.TButton", command=lambda e=example: self.edit_script(preset=e)).pack(side="left", padx=(0, round(6 * s)))

        box = section(T("What I know about you"))
        self.flow(ttk.Label(box, style="Small.TLabel", justify="left", text=T(
            "Tell me about yourself in your own words: your work, the people you mention, how you like to be answered. I keep it in mind with every answer."
        )), beside).pack(anchor="w", pady=(0, round(6 * s)))
        edge = max(1, round(s))
        field = tk.Frame(box, bg=theme.FIELD_EDGE, bd=0)
        field.pack(fill="x", padx=(0, beside))
        self.about = tk.Text(
            field, height=3, wrap="word", font=self.f_text, relief="flat", borderwidth=0, highlightthickness=0, undo=True,
            bg=theme.FIELD, fg=INK, insertbackground=INK, padx=round(8 * s), pady=round(6 * s),
        )
        self.about.pack(fill="x", padx=edge, pady=edge)
        self.about.insert("1.0", settings["ai_about"])
        self.about.bind("<FocusOut>", lambda e: self.change("ai_about", self.about.get("1.0", "end-1c").strip()[:600]))
        ttk.Frame(box, height=round(8 * s)).pack()
        self.switch(box, "ai_memory", T("Note down lasting things I tell you about myself"), T(
            "For example \"Aziz is my manager\" or \"I work at a bank\". Every note is listed here, and you can delete it."
        ), beside)
        self.notes_box = ttk.Frame(box)
        self.notes_box.pack(fill="x", pady=(round(2 * s), 0))
        self.notes_shown = None
        self.notes_clear = ttk.Button(box, text=T("Forget all notes..."), command=self.forget_notes)
        self.notes_clear.pack(anchor="w", pady=(round(8 * s), 0))

        box = section(T("Our conversation"))
        self.switch(box, "ai_keep_talk", T("Remember our conversation after a restart"), T(
            "The last 40 lines, kept on this computer, so that I know what we were talking about."
        ), beside)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(round(6 * s), 0))
        ttk.Button(row, text=T("Clear the conversation"), command=self.clear_talk).pack(side="left")
        self.talk_note = ttk.Label(row, style="Small.TLabel")
        self.talk_note.pack(side="left", padx=round(10 * s))

    def size_word(self, model) -> str:
        """An offline model by the name it has in this tab: Small, Standard, Better."""
        key = next((key for key, known in llm.MODELS.items() if known is model), "standard")
        return T(MODEL_WORDS[key])

    def model_label(self, name: str) -> str:
        """An online model as the list shows it: Claude's have plain names."""
        return T(cloud.PLAIN_NAMES[name]) if name in cloud.PLAIN_NAMES else name

    def model_named(self, label: str) -> str:
        """The model a line of the list (or something typed) stands for."""
        label = label.strip()
        return next((name for name in cloud.PLAIN_NAMES if T(cloud.PLAIN_NAMES[name]) == label), label)

    def brain_words(self) -> tuple:
        """How things stand, in a headline and a line under it."""
        ai = self.app.ai
        settings = self.app.settings
        service = ai.service()
        who = f"{T(service.service.name)}, {self.model_label(service.model)}"
        no_model = T("The online AI has your key, but no model is chosen yet.") + " " + T("Press Test: I ask the service which models it has and pick one.")
        if ai.both and service.ready() and ai.local is not None:
            if ai.online_down():
                status = T("No connection to the online AI right now: this computer answers ({model}).", model=self.size_word(ai.local))
                more = T("I try the online one again by myself, about once a minute.")
            else:
                status = T("Answers come from {who}, and from this computer when there is no connection.", who=who)
                more = T("What you write is sent to that service while it answers.")
        elif ai.both and service.ready():
            status = T("Answers come from {who}: ready.", who=who)
            more = T("There is no AI on this computer yet to take over when the connection is lost: download it below.")
        elif ai.both and ai.local is not None:
            status = T("Answers come from this computer ({model}): ready.", model=self.size_word(ai.local))
            more = no_model if settings["ai_key"] else T("The online half is not set up yet: it needs your key, below.")
        elif ai.both:
            status = T("My AI brain is being downloaded.") if ai.fetching else T("My AI brain is not set up yet.")
            more = T("\"Both\" wants the AI on this computer (a download, below) and your key for the online one. Either of them alone answers already.")
        elif ai.online:
            if ai.state == "ready":
                status = T("Answers come from {who}: ready.", who=who)
                more = T("What you write is sent to that service.")
            elif settings["ai_key"]:
                status = T("The online AI has your key, but no model is chosen yet.")
                more = T("Press Test: I ask the service which models it has and pick one.")
            else:
                status = T("The online AI needs your key.")
                more = T("Paste the key below and press Save. Until then I cannot answer questions.")
        elif ai.local is not None:
            status = T("Answers come from this computer ({model}): ready.", model=self.size_word(ai.local))
            more = T("Nothing you write is sent anywhere.")
        elif ai.fetching:
            status = T("My AI brain is being downloaded.")
            more = T("You can close this window: I will tell you when it is ready.")
        else:
            status = T("My AI brain is not set up yet.")
            more = T("Choose below where I should think: on this computer (downloaded once) or online, with your own key.")
        if ai.timing and ai.state == "ready":
            more += " " + T("Last answer: first word after {a} s, all of it after {b} s.", a=f"{ai.timing[0]:.1f}", b=f"{ai.timing[1]:.1f}")
        return status, more

    def _brain_progress(self) -> None:
        """The bar of the offline AI's download, which moves several times a second."""
        ai = self.app.ai
        if ai.fetching:
            if not self.brain_bar.winfo_ismapped():
                self.brain_bar.pack(anchor="w", before=self.brain_buttons, pady=(round(8 * self.s), round(2 * self.s)))
                self.brain_progress.pack(anchor="w", before=self.brain_buttons)
            self.brain_bar.configure(value=int(1000 * ai.done / max(ai.total, 1)))
            self.brain_progress.configure(text=setup_words(ai))
        else:
            self.brain_bar.pack_forget()
            self.brain_progress.pack_forget()

    def refresh_brain(self) -> None:
        app = self.app
        ai = app.ai
        settings = app.settings
        s = self.s
        typing_in = self.focused()
        ai.find_model()  # an online AI that has its key but no model yet asks the service for one (it does nothing otherwise)
        status, more = self.brain_words()
        self.brain_status.configure(text=status)
        self.brain_more.configure(text=more)
        self._brain_progress()
        for key, var in self.switches.items():
            var.set(bool(settings[key]))
        for key, (var, options) in self.picks.items():
            var.set(next((T(label) for value, label in options if value == settings[key]), T(options[0][1])))

        # on this computer
        self.ai_source.set(settings["ai_source"])
        self.brain_size.set(settings["ai_model"])
        chosen = ai.model
        here = ai.local is chosen
        size = llm.gb(ai.download_size())
        if ai.fetching:
            line = T("Downloading the {model}.", model=self.size_word(ai.fetched or chosen))
        elif here:
            line = T("The {model} is on this computer.", model=self.size_word(chosen))
        elif ai.local is not None:
            line = T("The {model} is not on this computer yet: a one-time download of {size}. Until then the {other} answers.", model=self.size_word(chosen), size=size, other=self.size_word(ai.local))
        else:
            line = T("Not on this computer yet: a one-time download of {size}. It continues where it stopped if interrupted.", size=size)
        if ai.error and not ai.fetching:
            line += "\n" + ai.error
        self.brain_line.configure(text=line)
        if ai.fetching:
            self.brain_fetch.configure(text=T("Stop"), style="TButton", state="normal")
        elif here:
            self.brain_fetch.configure(text=T("Already here"), style="TButton", state="disabled")
        else:
            self.brain_fetch.configure(text=T("Download ({size})", size=size), style="Accent.TButton", state="normal")
        self.ai_remove.configure(state="normal" if ai.engine.installed() and not ai.fetching else "disabled")

        # online
        service = cloud.SERVICES.get(settings["ai_service"], cloud.SERVICES["claude"])
        self.ai_service.set(T(service.name))
        names = list(service.models) or list(ai.found.get(settings["ai_service"], ()))
        if self.models_of != (settings["ai_service"], tuple(names)):
            self.models_of = (settings["ai_service"], tuple(names))
            self.ai_models.configure(values=[self.model_label(name) for name in names])
        if typing_in is not self.ai_models:
            self.ai_model_name.set(self.model_label(settings["ai_online_model"] or (service.models[0] if service.models else "")))
        if service.address:
            self.ai_address_row.pack_forget()
        else:
            self.ai_address_row.pack(fill="x", pady=round(3 * s), before=self.ai_online_end)
            if typing_in is not self.ai_address_field:
                self.ai_address.set(settings["ai_address"])
        self.ai_key_note.configure(text=T("A key is saved, locked to your Windows account. Type a new one to replace it.") if settings["ai_key"] else T("No key yet. You get one from the service's own website."))

        # what it knows
        if typing_in is not self.about and self.about.get("1.0", "end-1c").strip() != settings["ai_about"]:
            self.about.delete("1.0", "end")
            self.about.insert("1.0", settings["ai_about"])
        notes = app.store.notes()
        stamp = tuple((note["id"], note["text"]) for note in notes)
        if stamp != self.notes_shown:
            self.notes_shown = stamp
            for child in self.notes_box.winfo_children():
                child.destroy()
            self.flowing = [(label, inset) for label, inset in self.flowing if label.winfo_exists()]
            beside = round(22 * s)
            if not notes:
                self.flow(ttk.Label(self.notes_box, style="Faint.TLabel", justify="left", text=T("Nothing noted yet. Tell me something about yourself in Chat, or say \"remember that...\".")), beside).pack(anchor="w")
            for note in notes:
                row = ttk.Frame(self.notes_box)
                row.pack(fill="x", pady=round(1 * s))
                ttk.Button(row, text=T("Delete"), style="Chip.TButton", command=lambda i=note["id"]: self.delete_note(i)).pack(side="right", anchor="n", padx=(round(6 * s), beside))
                self.flow(ttk.Label(row, text="•  " + note["text"], justify="left"), beside + round(120 * s)).pack(side="left", anchor="w")
        self.notes_clear.configure(state="normal" if notes else "disabled")

        # the programs that may be read
        on = bool(settings["ai_may_read"])
        ticked = list(settings["ai_read_programs"])
        listed: dict = {}
        if on:
            listed = {program: name for program, name, _hwnd in reader.showing()}
            for program in ticked:
                listed.setdefault(program, app.read_name(program))
            # ... and what people read most, also while it is closed: "Try" opens it
            for place, row in app.store.places().items():
                if len(listed) < 14 and row.get("path") and row.get("category") in READ_KINDS and place == apps.base_stem(apps.stem_of(row["path"])):
                    listed.setdefault(place, row.get("name") or place)
        stamp = (on, tuple(sorted(listed.items())), tuple(ticked), bool(settings["ai_read_online"]))
        if stamp != self.read_shown:
            self.read_shown = stamp
            for child in self.read_box.winfo_children():
                child.destroy()
            self.flowing = [(label, inset) for label, inset in self.flowing if label.winfo_exists()]
            self.read_vars, self.read_result = {}, None
            beside, under = round(22 * s), round(44 * s)
            if on:
                self.flow(ttk.Label(self.read_box, style="Small.TLabel", justify="left", text=T(
                    "Which programs? Open the one you want me to read, then tick it here. \"Try\" shows whether I can read it: some programs do not let me."
                )), beside + under).pack(anchor="w", pady=(0, round(4 * s)))
                for program, name in sorted(listed.items(), key=lambda item: item[1].lower()):
                    row = ttk.Frame(self.read_box)
                    row.pack(fill="x")
                    var = tk.BooleanVar(value=program in ticked)
                    self.read_vars[program] = var
                    ttk.Button(row, text=T("Try"), style="Chip.TButton", command=lambda p=program, n=name: self.try_reading(p, n)).pack(side="right", padx=(round(6 * s), beside))
                    ttk.Checkbutton(row, text=name, variable=var, command=lambda p=program, n=name, v=var: self.tick_program(p, n, v.get())).pack(side="left")
                self.read_result = self.flow(ttk.Label(self.read_box, style="Small.TLabel", justify="left"), beside + under)
                self.read_result.pack(anchor="w", pady=(round(2 * s), 0))  # what "Try" found: under the list it belongs to
                ttk.Button(self.read_box, text=T("Look again for open programs"), style="Chip.TButton", command=self.refresh).pack(anchor="w", pady=(round(6 * s), round(6 * s)))
                self.read_where.set("online" if settings["ai_read_online"] else "local")
                for value, label in (("local", T("What I read goes only to my AI on this computer")), ("online", T("It may also go to the online AI, when that one answers"))):
                    ttk.Radiobutton(self.read_box, text=label, value=value, variable=self.read_where, command=lambda v=value: self.change("ai_read_online", v == "online")).pack(anchor="w")
                ttk.Frame(self.read_box, height=round(8 * s)).pack()

        # the daily scripts
        scripts = app.store.scripts()
        stamp = (app.today,) + tuple(tuple(sorted(script.items(), key=lambda item: item[0])) for script in scripts)
        if stamp != self.scripts_shown:
            self.scripts_shown = stamp
            for child in self.scripts_box.winfo_children():
                child.destroy()
            self.flowing = [(label, inset) for label, inset in self.flowing if label.winfo_exists()]
            self.script_vars = []
            beside, under = round(22 * s), round(44 * s)
            if not scripts:
                self.flow(ttk.Label(self.scripts_box, style="Faint.TLabel", justify="left", text=T("No scripts yet.")), beside).pack(anchor="w")
            for script in scripts:
                number = script["id"]
                row = ttk.Frame(self.scripts_box)
                row.pack(fill="x", pady=(round(4 * s), 0))
                for at, (label, pressed) in enumerate(((T("Delete"), self.delete_script), (T("Edit"), self.edit_script), (T("Run now"), self.run_script))):
                    ttk.Button(row, text=label, style="Chip.TButton", command=lambda i=number, f=pressed: f(i)).pack(side="right", anchor="n", padx=(round(4 * s), beside if at == 0 else 0))
                on = tk.BooleanVar(value=bool(script["enabled"]))
                self.script_vars.append(on)
                when = f"{script['at'] // 60:02d}:{script['at'] % 60:02d}"
                ttk.Checkbutton(row, variable=on, style="Switch.TCheckbutton", text=f"{when}   {script['name']}", command=lambda i=number, v=on: self.toggle_script(i, v.get())).pack(side="left")
                self.flow(ttk.Label(self.scripts_box, style="Small.TLabel", justify="left", text=self.script_words(script)), beside + under).pack(anchor="w", padx=(under, 0))

    def tick_program(self, program: str, name: str, on: bool) -> None:
        """A program is ticked (the cat may read it) or the tick is taken away."""
        settings = self.app.settings
        programs = [one for one in settings["ai_read_programs"] if one != program] + ([program] if on else [])
        settings["ai_read_names"] = {**settings["ai_read_names"], program: name}
        self.change("ai_read_programs", programs)

    def try_reading(self, program: str, name: str) -> None:
        """Read the program's window once, now, and say how much came of it. Counted only:
        nothing of it is shown or kept."""
        label = self.read_result
        if label is None:
            return
        found: dict = {}
        path = (self.app.store.places().get(program) or {}).get("path") or ""

        def work() -> None:
            hwnd = reader.window_of(program)
            if not hwnd and path and os.path.isfile(path):  # not open: the cat starts it, and waits for its window
                try:
                    os.startfile(path)
                except OSError:
                    pass
                for _ in range(40):
                    time.sleep(0.5)
                    hwnd = reader.window_of(program)
                    if hwnd:
                        time.sleep(2.5)  # let it draw what it has
                        break
            found.update(seen=reader.read(hwnd))

        label.configure(text=T("Reading {name}...", name=name))
        threading.Thread(target=work, name="try-reading", daemon=True).start()

        def look() -> None:
            if not label.winfo_exists():
                return
            if "seen" not in found:
                label.after(120, look)
                return
            seen = found.pop("seen")
            size = len(seen.text)
            if seen.why in ("gone", "hidden"):
                label.configure(text=T("{name} is not showing on the screen right now.", name=name))
            elif size >= 40:
                label.configure(text=T("{name}: I can read it ({n} characters just now).", name=name, n=size))
            else:
                label.configure(text=T("{name}: its window gives me almost nothing to read. Some programs do not let me.", name=name))

        label.after(120, look)

    def script_words(self, script: dict) -> str:
        """Under a script's name: when it runs, whether it acts by itself, and how it begins."""
        days = script["days"]
        if days == EVERY_DAY:
            when = T("every day")
        elif days == WORKDAYS:
            when = T("on workdays")
        else:
            when = ", ".join(T(tasks.WEEKDAYS[i]) for i in range(7) if (days >> i) & 1)
        parts = [when, T("may act by itself") if script["acts"] else T("asks before it acts")]
        if script.get("look"):
            parts.insert(1, T("looks at {name}", name=self.app.read_name(script["look"])))
        if script["last"] == self.app.today:
            parts.append(T("ran today"))
        what = " ".join(script["text"].split())
        return " · ".join(parts) + "\n" + (what if len(what) <= 120 else what[:119].rstrip() + "…")

    def edit_script(self, number=None, preset=None) -> None:
        """Open the small window for a new script, for one of the examples, or for a script there is."""
        ScriptEditor(self, self.app.store.script(number) if number else None, preset)

    def toggle_script(self, number: int, on: bool) -> None:
        self.app.store.update_script(number, enabled=int(on))
        self.refresh_brain()

    def run_script(self, number: int) -> None:
        script = self.app.store.script(number)
        if script:
            self.app.run_script(script, by_hand=True)

    def delete_script(self, number: int) -> None:
        script = self.app.store.script(number)
        if script and messagebox.askyesno(APP_NAME, T('Delete the script "{name}"?', name=script["name"]), parent=self.win):
            self.app.store.delete_script(number)
            self.refresh_brain()

    def say_result(self, text: str, colour: str = "") -> None:
        """The line under the Test button. It takes no room while it has nothing to say."""
        self.ai_result.configure(text=text, foreground=colour or FAINT)
        if text:
            self.ai_result.pack(anchor="w", pady=(round(6 * self.s), 0))
        else:
            self.ai_result.pack_forget()

    def models_opened(self) -> None:
        """The list of models was opened: if it is empty and there is a key, fetch it."""
        if not self.ai_models.cget("values") and self.app.settings["ai_key"]:
            self.fetch_models()

    def pick_model(self) -> None:
        self.change("ai_online_model", self.model_named(self.ai_model_name.get()))

    def pick_service(self) -> None:
        key = self.service_names.get(self.ai_service.get(), "claude")
        if key == self.app.settings["ai_service"]:
            return
        self.app.settings["ai_online_model"] = ""  # a model of one service means nothing to another
        self.app.settings["ai_address"] = ""
        self.ai_address.set("")
        self.say_result("")
        self.change("ai_service", key)
        self.refresh_brain()
        if self.app.settings["ai_key"] and self.app.ai.service().reachable():
            self.app.ai.list_models()  # its own list, and a model picked from it

    def save_key(self) -> None:
        """Keep the key that was typed. A key that plainly belongs to another service
        than the one chosen moves the choice to that service, and the cat says so."""
        typed = self.ai_key.get().strip()
        if not typed:
            return
        settings = self.app.settings
        self.ai_key.set("")
        said = T("Key saved.")
        whose = cloud.guess_service(typed)
        by_hand = settings["ai_service"] == "other" and (self.ai_address.get().strip() or settings["ai_address"])  # an address typed on purpose stays
        if whose and whose != settings["ai_service"] and not by_hand:
            settings["ai_service"], settings["ai_online_model"], settings["ai_address"] = whose, "", ""
            self.ai_address.set("")
            said = T("This is a key for {service}, so I switched the service to it.", service=T(cloud.SERVICES[whose].name))
        settings["ai_key"] = ""  # so that the same key typed again is taken as a change too
        self.change("ai_key", cloud.lock(typed))
        if not self.app.ai.online:
            said += " " + T("Choose \"Online, with my own key\" above to use it.")
        self.say_result(said)
        if self.app.ai.service().reachable():
            self.app.ai.list_models()  # the list arrives by itself, and a model is picked from it

    def forget_key(self) -> None:
        self.ai_key.set("")
        self.say_result("")
        self.change("ai_key", "")
        self.refresh_brain()

    def test_brain(self) -> None:
        """Ask whoever answers one small question, and say how long it took. With "both"
        chosen, each of the two is asked, one after the other."""
        ai = self.app.ai
        self.tested, self.test_next = [], ""
        which = "offline"
        if ai.online:
            self.save_key()
            self.change("ai_address", self.ai_address.get().strip())
            service = ai.service()
            if service.key and service.address:
                which = "online"
                if ai.both and ai.local is not None:
                    self.test_next = "offline"
            elif not ai.both or ai.local is None:
                self.say_result(T("First paste your key and press Save.") if not service.key else T("First give the address of the service."), BAD)
                return
        if which == "offline" and ai.local is None:
            self.say_result(T("There is no AI on this computer yet. Download it first, or choose the online one."), BAD)
            return
        self.say_result(T("Asking..."))
        self.ai_test.configure(state="disabled")
        ai.test(which)

    def fetch_models(self) -> None:
        self.save_key()
        self.change("ai_address", self.ai_address.get().strip())
        if not self.app.ai.service().reachable():
            self.say_result(T("First paste your key and press Save."), BAD)
            return
        self.say_result(T("Asking..."))
        self.app.ai.list_models()

    def online_answer(self, what: str, ok: bool, result) -> None:
        """The test was answered, or the service sent its list of models."""
        if what == "models":
            self.ai_test.configure(state="normal")
            if not ok:
                self.say_result(str(result), BAD)
            else:
                said = T("Models found: {n}.", n=len(result["names"] or ()))
                if result["model"]:
                    said += " " + T("I picked {model}. You can choose another.", model=self.model_label(result["model"]))
                self.say_result(said)
        else:
            tested = getattr(self, "tested", [])
            tested.append((ok, T("It works: {model} answered in {s} s.", model=self.model_label(result["model"]), s=f"{result['seconds']:.1f}") if ok else str(result)))
            more, self.test_next = getattr(self, "test_next", ""), ""
            lines = "\n".join(line for _, line in tested)
            if more:  # the other of the two is asked now
                self.say_result(lines + "\n" + T("Asking..."))
                self.app.ai.test(more)
            else:
                self.ai_test.configure(state="normal")
                # all fine: green; one of the two fine: amber (the other says what is wrong); none: red
                self.say_result(lines, GOOD if all(fine for fine, _ in tested) else WARN if any(fine for fine, _ in tested) else BAD)
                self.tested = []
        if self.visible and self.current() == "brain":
            self.refresh_brain()

    def remove_ai(self) -> None:
        if messagebox.askyesno(APP_NAME, T("Delete the offline AI and its model from this computer?\n\nYou can set it up again later; that means downloading it again."), parent=self.win):
            self.app.ai.remove()
            self.refresh()

    def delete_note(self, note_id: int) -> None:
        self.app.store.delete_note(note_id)
        self.refresh_brain()

    def forget_notes(self) -> None:
        if messagebox.askyesno(APP_NAME, T("Forget everything I noted down about you?\n\nWhat you wrote about yourself in the box stays."), parent=self.win):
            self.app.store.clear_notes()
            self.refresh_brain()

    def clear_talk(self) -> None:
        self.app.clear_conversation()
        self.talk_note.configure(text=T("Cleared."))

    def change(self, key: str, value) -> None:
        if self.app.settings.get(key) == value:
            return
        if key == "language":  # this window is rebuilt in the new language, so leave it first
            self.app.root.after(60, lambda: self.app.set_language(value))
            return
        self.app.settings[key] = value
        self.app.apply_settings()
        if key in ("name", "coat") or key.startswith("ai_"):
            self.refresh()


# --------------------------------------------------------------------------- small windows

def ask(app, title: str, prompt: str, on_ok, tick_label: str = "", initial: str = "") -> None:
    """A one-line question near the cat. on_ok(text, ticked) runs if something was typed.
    `initial` is what stands in the field to begin with, selected, ready to be typed over."""
    s = app.ui_scale
    theme.use(app)
    win = tk.Toplevel(app.root)
    win.title(title)
    win.configure(bg=CARD)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    frame = ttk.Frame(win, padding=round(18 * s))
    frame.pack()
    ttk.Label(frame, text=prompt, wraplength=round(360 * s), justify="left").pack(anchor="w")
    text = tk.StringVar(value=initial)
    entry = ttk.Entry(frame, textvariable=text, width=46)
    entry.pack(fill="x", pady=round(10 * s))
    entry.select_range(0, "end")
    entry.icursor("end")
    ticked = tk.BooleanVar(value=False)
    if tick_label:
        ttk.Checkbutton(frame, text=tick_label, variable=ticked).pack(anchor="w", pady=(0, round(10 * s)))

    def accept(*_):
        value = text.get().strip()
        win.destroy()
        if value:
            on_ok(value, ticked.get())

    row = ttk.Frame(frame)
    row.pack(fill="x")
    ttk.Button(row, text=T("Cancel"), command=win.destroy).pack(side="right")
    ttk.Button(row, text=T("OK"), command=accept, style="Accent.TButton").pack(side="right", padx=round(8 * s))
    win.bind("<Return>", accept)
    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    _place_window(win, app, win.winfo_reqwidth(), win.winfo_reqheight())

    def focus():
        if win.winfo_exists():
            win.lift()
            win.focus_force()
            entry.focus_set()

    win.after(60, focus)


class ScriptEditor:
    """The small window in which a daily script is written or changed."""

    def __init__(self, panel, script=None, preset=None):
        self.panel, self.script = panel, script
        app = self.app = panel.app
        s = app.ui_scale
        t = theme.use(app)
        name, at, days, what, acts, look = "", 9 * 60, EVERY_DAY, "", False, ""
        if preset:
            name, at, days, what = T(preset[0]), preset[1], preset[2], T(preset[3])
        if script:
            name, at, days, what, acts, look = script["name"], script["at"], script["days"], script["text"], bool(script["acts"]), script.get("look") or ""
        win = self.win = tk.Toplevel(app.root)
        win.title(T("Daily script"))
        win.configure(bg=CARD)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=round(18 * s))
        frame.pack()
        wrap, under, edge = round(440 * s), round(44 * s), max(1, round(s))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text=T("Name")).pack(side="left")
        self.name = tk.StringVar(value=name)
        self.name_field = ttk.Entry(row, textvariable=self.name, width=34)
        self.name_field.pack(side="right")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(round(8 * s), 0))
        ttk.Label(row, text=T("Time")).pack(side="left")
        self.minute = tk.StringVar(value=f"{at % 60:02d}")
        ttk.Spinbox(row, from_=0, to=59, increment=5, textvariable=self.minute, width=4, format="%02.0f", wrap=True).pack(side="right")
        ttk.Label(row, text=":").pack(side="right", padx=round(4 * s))
        self.hour = tk.StringVar(value=f"{at // 60:02d}")
        ttk.Spinbox(row, from_=0, to=23, textvariable=self.hour, width=4, format="%02.0f", wrap=True).pack(side="right")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(round(8 * s), 0))
        self.days: list = []
        for i, day in enumerate(tasks.WEEKDAYS):
            var = tk.BooleanVar(value=bool((days >> i) & 1))
            self.days.append(var)
            ttk.Checkbutton(row, text=T(day), variable=var).pack(side="left", padx=(0, round(10 * s)))

        ttk.Label(frame, text=T("What should I do? Write it the way you would say it to me."), wraplength=wrap, justify="left").pack(anchor="w", pady=(round(12 * s), round(4 * s)))
        field = tk.Frame(frame, bg=theme.FIELD_EDGE, bd=0)
        field.pack(fill="x")
        self.text = tk.Text(
            field, width=54, height=5, wrap="word", font=t.f_text, relief="flat", borderwidth=0, highlightthickness=0, undo=True,
            bg=theme.FIELD, fg=INK, insertbackground=INK, padx=round(8 * s), pady=round(6 * s),
        )
        self.text.pack(fill="x", padx=edge, pady=edge)
        self.text.insert("1.0", what)

        # A program to read first. Only those the person ticked in the AI brain tab are
        # offered (and the one this script was given before, should it be unticked since).
        allowed = list(app.settings["ai_read_programs"]) if app.settings["ai_may_read"] else []
        if look and look not in allowed:
            allowed.append(look)
        self.looks = [("", T("nothing"))] + [(program, app.read_name(program)) for program in allowed]
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(round(10 * s), 0))
        ttk.Label(row, text=T("Look at first")).pack(side="left")
        self.look = tk.StringVar(value=dict(self.looks).get(look, T("nothing")))
        self.look_field = ttk.Combobox(row, textvariable=self.look, state="readonly" if allowed else "disabled", values=[label for _program, label in self.looks], width=26)
        self.look_field.pack(side="right")
        ttk.Label(frame, style="Small.TLabel", wraplength=wrap, justify="left", text=T(
            "A program whose window I read before I answer: \"tell me who is waiting for a reply\". Tick it first in the AI brain tab, under \"Read what other programs show\". What such a script wants done is always shown with a \"Do it\" button."
        )).pack(anchor="w", pady=(round(2 * s), 0))

        self.acts = tk.BooleanVar(value=acts)
        ttk.Checkbutton(frame, text=T("May act by itself"), variable=self.acts, style="Switch.TCheckbutton").pack(anchor="w", pady=(round(10 * s), 0))
        ttk.Label(frame, style="Small.TLabel", wraplength=wrap - under, justify="left", text=T(
            "Off: what this script wants to do (open a program, add a reminder, start the timer) is shown with a \"Do it\" button and waits for you. On: it is done at its time and shown with Undo."
        )).pack(anchor="w", padx=(under, 0))

        self.problem = ttk.Label(frame, style="Bad.TLabel", wraplength=wrap, justify="left")
        self.problem.pack(anchor="w", pady=(round(6 * s), 0))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(round(4 * s), 0))
        ttk.Button(row, text=T("Cancel"), command=win.destroy).pack(side="right")
        ttk.Button(row, text=T("Save"), command=self.save, style="Accent.TButton").pack(side="right", padx=round(8 * s))
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        _place_window(win, app, win.winfo_reqwidth(), win.winfo_reqheight())

        def focus():
            if win.winfo_exists():
                win.lift()
                win.focus_force()
                (self.text if name else self.name_field).focus_set()

        win.after(60, focus)

    def save(self) -> None:
        store = self.app.store
        what = self.text.get("1.0", "end-1c").strip()[:1000]
        name = " ".join(self.name.get().split())[:30]
        days = sum(1 << i for i, var in enumerate(self.days) if var.get())
        try:
            at = (int(float(self.hour.get())) % 24) * 60 + int(float(self.minute.get())) % 60
        except ValueError:
            self.problem.configure(text=T("The time should be two numbers, like 09:00."))
            return
        if not what:
            self.problem.configure(text=T("Write what I should do."))
            return
        if not days:
            self.problem.configure(text=T("Tick at least one day."))
            return
        if not name:
            name = what[:30]
        look = next((program for program, label in self.looks if label == self.look.get()), "") or None
        number = self.script["id"] if self.script else store.add_script(name, what, at, days, self.acts.get(), look)
        if not number:
            self.problem.configure(text=T("That is as many scripts as I can keep: {n}.", n=SCRIPTS_MOST))
            return
        if self.script:
            store.update_script(number, name=name, text=what, at=at, days=days, acts=int(self.acts.get()), look=look)
        # A script written now for a time that is already past today first runs tomorrow:
        # "Run now" is there for trying it out.
        clock = dt.datetime.now()
        if (self.script is None or self.script["at"] != at) and clock.hour * 60 + clock.minute >= at:
            store.update_script(number, last=self.app.today)
        self.win.destroy()
        self.panel.refresh()


class Welcome:
    """First start: a name, a coat, and a clear say over what may be learned and fetched."""

    def __init__(self, app):
        self.app = app
        s = app.ui_scale
        t = theme.use(app)
        settings = app.settings
        win = self.win = tk.Toplevel(app.root)
        win.title(T("Welcome to {app}", app=APP_NAME))
        win.configure(bg=CARD)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.start)
        bg = self.bg = CARD
        wrap = round(500 * s)
        under = round(44 * s)
        frame = ttk.Frame(win, padding=(round(22 * s), round(16 * s)))
        frame.pack()
        hints: list = []  # the small grey lines: the first to go if the screen is too low for all of this

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(0, round(8 * s)))
        ttk.Label(row, text="Language  /  Язык  /  Тил", style="Small.TLabel").pack(side="left")
        self.language = tk.StringVar(value=i18n.LANGUAGES.get(settings.get("language"), "English"))
        languages = ttk.Combobox(row, textvariable=self.language, state="readonly", values=list(i18n.LANGUAGES.values()), width=14)
        languages.pack(side="right")
        languages.bind("<<ComboboxSelected>>", lambda e: self.speak())

        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.cat = tk.Label(top, bd=0, bg=bg)
        self.cat.pack(side="left")
        words = ttk.Frame(top)
        words.pack(side="left", padx=round(14 * s))
        beside = wrap - round(120 * s)
        ttk.Label(words, text=T("Hi! I'm your new desk cat."), style="Title.TLabel", wraplength=beside, justify="left").pack(anchor="w")
        ttk.Label(words, text=T("I sit on the window you work in, keep your focus timer and reminders, and learn your routine so I can nudge you at the right moment."), wraplength=beside, justify="left").pack(anchor="w", pady=(round(2 * s), 0))

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(round(10 * s), round(4 * s)))
        ttk.Label(row, text=T("What will you call me?")).pack(side="left")
        self.name = tk.StringVar(value=settings["name"])
        ttk.Entry(row, textvariable=self.name, width=22).pack(side="right")

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text=T("Pick a coat")).pack(side="left")
        self.coat = tk.StringVar(value=settings["coat"])
        for coat in reversed(sprites.COAT_NAMES):  # packed from the right, so the first coat ends up leftmost
            image = app.images.get(sprites.face_rows(), coat, rim=False, scale=max(2, round(2 * s)), bg=bg)
            tk.Radiobutton(
                row, image=image, variable=self.coat, value=coat, indicatoron=False, bd=0, relief="flat", offrelief="flat", overrelief="flat",
                bg=bg, selectcolor=theme.SELECT, activebackground=theme.HOT, highlightthickness=0, padx=round(5 * s), pady=round(5 * s), command=self.preview,
            ).pack(side="right", padx=(round(4 * s), 0))

        ttk.Label(frame, text=T("What may I learn about your work?"), style="Head.TLabel").pack(anchor="w", pady=(round(12 * s), 0))
        ttk.Label(frame, text=T("Everything I learn stays in a folder on this computer and is sent nowhere. You can change this or erase it any time in Settings."), style="Small.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(0, round(4 * s)))
        self.ticks: dict = {}
        for key, text, hint in (
            ("learn_routine", T("My routine: which programs I use and when"), T("Program names and minutes. Never what you type or see.")),
            ("learn_sites", T("Well-known sites in my browser"), T("YouTube, Gmail, GitHub and the like, by the tab's title. Only the site's name is kept.")),
            ("learn_media", T("Notice what I listen to and watch"), T("Titles and artists of what plays, for music and video suggestions.")),
        ):
            var = tk.BooleanVar(value=bool(settings[key]))
            self.ticks[key] = var
            ttk.Checkbutton(frame, text=text, variable=var, style="Switch.TCheckbutton").pack(anchor="w")
            hints.append(ttk.Label(frame, text=hint, style="Small.TLabel", wraplength=wrap - under, justify="left"))
            hints[-1].pack(anchor="w", padx=(under, 0), pady=(0, round(2 * s)))

        var = tk.BooleanVar(value=bool(settings["weather"]))
        self.ticks["weather"] = var
        ttk.Checkbutton(frame, text=T("Tell me the weather (I look it up online)"), variable=var, style="Switch.TCheckbutton").pack(anchor="w", pady=(round(6 * s), 0))
        hints.append(ttk.Label(frame, text=T("The one thing that uses the internet by itself: a free weather service is asked for your city's weather."), style="Small.TLabel", wraplength=wrap - under, justify="left"))
        hints[-1].pack(anchor="w", padx=(under, 0), pady=(0, round(2 * s)))

        ttk.Label(frame, text=T("My offline AI brain"), style="Head.TLabel").pack(anchor="w", pady=(round(10 * s), round(2 * s)))
        self.fetch = tk.BooleanVar(value=app.ai.state == "missing")
        size = app.ai.download_size()
        if app.ai.state == "ready":
            ttk.Label(frame, text=T("It is already on this computer. We can talk right away."), style="Small.TLabel", wraplength=wrap, justify="left").pack(anchor="w")
        else:
            ttk.Checkbutton(frame, text=T("Set it up now, so we can talk ({size}, downloaded once)", size=llm.gb(size)), variable=self.fetch, style="Switch.TCheckbutton").pack(anchor="w")
            hints.append(ttk.Label(frame, text=T("A real language AI that runs only on this computer. After the download it needs no internet and sends nothing anywhere. You can also do this later, from Chat."), style="Small.TLabel", wraplength=wrap - under, justify="left"))
            hints[-1].pack(anchor="w", padx=(under, 0))

        ttk.Button(frame, text=T("Start"), command=self.start, style="Accent.TButton", width=-10).pack(anchor="e", pady=(round(12 * s), 0))
        win.bind("<Return>", lambda e: self.start())
        self.preview()
        win.update_idletasks()
        # On a low screen (a small laptop, or large text) the Start button must still be
        # reachable: the grey lines of explanation give way, the last ones first.
        room = _area(app).height - round(60 * s)
        while hints and win.winfo_reqheight() > room:
            hints.pop().pack_forget()
            win.update_idletasks()
        _place_window(win, app, win.winfo_reqwidth(), win.winfo_reqheight())
        win.after(80, lambda: (win.lift(), win.focus_force()) if win.winfo_exists() else None)

    def speak(self) -> None:
        """Another language was picked: show this same screen again in it."""
        code = next((code for code, name in i18n.LANGUAGES.items() if name == self.language.get()), "en")
        settings = self.app.settings
        if code == settings.get("language"):
            return
        settings["name"] = self.name.get().strip()[:20] or settings["name"]
        for key, var in self.ticks.items():  # nothing is learned from these until Start is pressed
            settings[key] = bool(var.get())
        settings["language"] = code
        i18n.load(code)
        self.win.destroy()
        self.app.root.after(30, self.app.welcome)

    def preview(self) -> None:
        self.app.settings["coat"] = self.coat.get()  # the cat on screen changes coat as you pick
        self.cat.configure(image=self.app.images.get(sprites.frame("sit", 2000, mood="happy"), self.coat.get(), rim=False, scale=max(2, round(2 * self.app.ui_scale)), bg=self.bg))

    def start(self) -> None:
        app = self.app
        settings = app.settings
        settings["name"] = self.name.get().strip()[:20] or settings["name"]
        settings["coat"] = self.coat.get()
        for key, var in self.ticks.items():
            settings[key] = bool(var.get())
        settings["first_run_done"] = True
        self.win.destroy()
        app.apply_settings()
        app.store.put("seen_version", __version__)
        hello = T("Hi, I'm {name}! Double-click me to talk, right-click me for my menu, and drag me wherever you like.", name=settings["name"])
        if self.fetch.get() and app.ai.state == "missing":
            app.ai.setup()
            hello += " " + T("I am fetching my AI brain now and will tell you when it is ready.")
        app.voice.say(hello, kind="reply", ttl=16, emote="happy")
