"""Two small windows of their own: games to play with the cat, and habits with goals for
the week, the month and the year.

The games: catching a mouse that shows itself for a shorter and shorter moment (reaction),
remembering which squares lit up and a number that grows (memory), and a quiz about the
person's own yesterday, made from what the cat has seen (or sums, where it has seen
nothing yet). Best results are kept; nothing else is.
"""
from __future__ import annotations

import datetime as dt
import random
import time
import tkinter as tk
from tkinter import ttk

import re

from . import assistant, theme, translit
from .i18n import N_, T
from .theme import CARD, FAINT, GOOD, INK

AMBER, FIELD, GREY, DARK = "#FFCF4A", "#F4F0E6", "#9AA0AE", "#5B6070"


def _window(app, title: str):
    from .panel import _place_window

    theme.use(app)
    win = tk.Toplevel(app.root)
    win.title(title)
    win.configure(bg=CARD)
    win.resizable(False, False)
    frame = ttk.Frame(win, padding=round(16 * app.ui_scale))
    frame.pack(fill="both", expand=True)
    win.bind("<Escape>", lambda e: win.destroy())

    def place() -> None:
        win.update_idletasks()
        _place_window(win, app, win.winfo_reqwidth(), win.winfo_reqheight())
        win.lift()

    return win, frame, place


# --------------------------------------------------------------------------- games

class Games:
    """The list of games, and the one being played, in one window."""

    def __init__(self, app):
        self.app = app
        self.s = app.ui_scale
        self.win, self.frame, self.place = _window(app, T("Play with me"))
        self.after = None
        self.hunt = None  # the game on the whole screen, while it runs
        self.win.bind("<Destroy>", lambda e: self.hunt.stop() if e.widget is self.win and self.hunt is not None else None)
        self.menu()

    def clear(self) -> None:
        if self.after is not None:
            try:
                self.win.after_cancel(self.after)
            except tk.TclError:
                pass
            self.after = None
        for child in self.frame.winfo_children():
            child.destroy()

    def later(self, ms: int, fn) -> None:
        self.after = self.win.after(ms, fn)

    def best(self, game: str) -> int:
        return int(self.app.store.get("game:" + game, 0) or 0)

    def keep(self, game: str, score: int) -> bool:
        """True if this is a new best."""
        if score > self.best(game):
            self.app.store.put("game:" + game, score)
            return True
        return False

    def menu(self) -> None:
        self.clear()
        s = self.s
        ttk.Label(self.frame, text=T("What shall we play?"), font=("Segoe UI Semibold", 12)).pack(anchor="w")
        games = (
            (T("Catch the mouse"), T("On your whole screen: it shows itself for a moment, somewhere new each time, and faster with every level. Trains your reaction."), "mouse", self.mouse, T("level {n}")),
            (T("Which squares?"), T("Some squares light up. Remember them and click them. Each round one more."), "grid", self.grid, T("{n} squares")),
            (T("The long number"), T("A number shows for a moment. Type it from memory. Each round one digit more."), "number", self.number, T("{n} digits")),
            (T("About your day"), T("A few questions about your own yesterday: what you worked in, what you finished."), "quiz", self.quiz, T("{n} right")),
            (T("Chase my pointer"), T("The old game: move the mouse, and I catch it."), "", self.chase, ""),
        )
        for title, about, key, start, unit in games:
            row = ttk.Frame(self.frame)
            row.pack(fill="x", pady=(round(10 * s), 0))
            ttk.Button(row, text=T("Play"), style="Accent.TButton", command=start).pack(side="right", anchor="n", padx=(round(10 * s), 0))
            best = self.best(key) if key else 0
            ttk.Label(row, text=title + (("   ·   " + T("best: {what}", what=unit.format(n=best))) if best else ""), font=("Segoe UI Semibold", 10)).pack(anchor="w")
            ttk.Label(row, text=about, style="Small.TLabel", wraplength=round(360 * s), justify="left").pack(anchor="w")
        self.place()

    def over(self, game: str, score: int, words: str, again) -> None:
        """A game has ended: say how it went, and offer another round."""
        record = self.keep(game, score)
        self.clear()
        s = self.s
        ttk.Label(self.frame, text=words, font=("Segoe UI Semibold", 12), wraplength=round(420 * s), justify="left").pack(anchor="w")
        if record and score:
            ttk.Label(self.frame, text=T("That is your best so far!"), foreground=GOOD).pack(anchor="w", pady=(round(4 * s), 0))
        row = ttk.Frame(self.frame)
        row.pack(anchor="w", pady=(round(14 * s), 0))
        ttk.Button(row, text=T("Again"), style="Accent.TButton", command=again).pack(side="left")
        ttk.Button(row, text=T("Other games"), command=self.menu).pack(side="left", padx=round(8 * s))
        self.app.store.log("play", {"game": game, "score": score})
        self.place()

    def head(self, title: str):
        self.clear()
        row = ttk.Frame(self.frame)
        row.pack(fill="x")
        ttk.Button(row, text=T("Other games"), style="Chip.TButton", command=self.menu).pack(side="right")
        ttk.Label(row, text=title, font=("Segoe UI Semibold", 12)).pack(side="left")
        status = ttk.Label(self.frame, style="Small.TLabel")
        status.pack(anchor="w", pady=(round(2 * self.s), round(6 * self.s)))
        return status

    def chase(self) -> None:
        self.win.destroy()
        self.app.chase_pointer()

    # --- catch the mouse
    def mouse(self) -> None:
        """Played on the whole screen (the one the pointer is on). The screen is dimmed a
        little by a window that takes every click, so that a click beside the mouse cannot
        land in the program underneath; the mouse itself is drawn on a see-through window
        above it; a small bar at the top says how the game stands."""
        self.clear()
        self.win.withdraw()
        self.hunt = Hunt(self)
        self.hunt.start()

    def hunt_over(self, level: int, times: list) -> None:
        self.hunt = None
        self.win.deiconify()
        middle = sorted(times)[len(times) // 2] if times else 0.0
        words = T("You got to level {level} and caught {n} mice. Your usual reaction: {ms} ms.", level=level, n=len(times), ms=round(middle * 1000)) if times else T("The mouse was quicker this time.")
        self.over("mouse", level if times else 0, words, self.mouse)

    # --- which squares
    def grid(self) -> None:
        s = self.s
        status = self.head(T("Which squares?"))
        side, cell, gap = 5, round(54 * s), round(6 * s)
        canvas = tk.Canvas(self.frame, width=side * (cell + gap) + gap, height=side * (cell + gap) + gap, bg=CARD, highlightthickness=0)
        canvas.pack()
        state = {"count": 3, "lit": set(), "picked": set(), "open": False}

        def paint(show: bool) -> None:
            canvas.delete("all")
            for index in range(side * side):
                x, y = gap + (index % side) * (cell + gap), gap + (index // side) * (cell + gap)
                colour = FIELD
                if show and index in state["lit"]:
                    colour = AMBER
                elif index in state["picked"]:
                    colour = AMBER if index in state["lit"] else "#E58A8A"
                canvas.create_rectangle(x, y, x + cell, y + cell, fill=colour, outline="#DDD6C4", tags=f"cell{index}")

        def round_() -> None:
            state["lit"] = set(random.sample(range(side * side), state["count"]))
            state["picked"], state["open"] = set(), False
            status.configure(text=T("Remember the {n} yellow squares...", n=state["count"]))
            paint(True)
            self.later(900 + 260 * state["count"], hide)

        def hide() -> None:
            state["open"] = True
            status.configure(text=T("Now click them."))
            paint(False)

        def click(event) -> None:
            if not state["open"]:
                return
            column, row = (event.x - gap) // (cell + gap), (event.y - gap) // (cell + gap)
            if not (0 <= column < side and 0 <= row < side):
                return
            index = row * side + column
            if index in state["picked"]:
                return
            state["picked"].add(index)
            paint(False)
            if index not in state["lit"]:
                state["open"] = False
                paint(True)
                done = state["count"] - 1
                self.later(1100, lambda: self.over("grid", done if done >= 3 else 0, T("You remembered {n} squares at once.", n=done) if done >= 3 else T("That one was not lit. Try once more?"), self.grid))
            elif state["picked"] >= state["lit"]:
                state["open"] = False
                state["count"] = min(state["count"] + 1, side * side - 1)
                status.configure(text=T("Right!"))
                self.later(700, round_)

        canvas.bind("<Button-1>", click)
        self.place()
        self.later(500, round_)

    # --- the long number
    def number(self) -> None:
        s = self.s
        status = self.head(T("The long number"))
        shown = ttk.Label(self.frame, font=("Consolas", 26, "bold"), width=16, anchor="center")
        shown.pack(pady=round(12 * s))
        typed = tk.StringVar()
        field = ttk.Entry(self.frame, textvariable=typed, font=("Consolas", 16), width=18, justify="center", state="disabled")
        field.pack()
        state = {"digits": 4, "number": ""}

        def round_() -> None:
            state["number"] = "".join(random.choice("0123456789") for _ in range(state["digits"]))
            typed.set("")
            field.configure(state="disabled")
            shown.configure(text=" ".join(state["number"][i:i + 3] for i in range(0, len(state["number"]), 3)), foreground=INK)
            status.configure(text=T("Remember these {n} digits...", n=state["digits"]))
            self.later(900 + 550 * state["digits"], ask)

        def ask() -> None:
            shown.configure(text="?")
            status.configure(text=T("Type the number and press Enter."))
            field.configure(state="normal")
            field.focus_set()

        def answer(_event=None) -> None:
            if str(field.cget("state")) != "normal":
                return
            said = "".join(ch for ch in typed.get() if ch.isdigit())
            field.configure(state="disabled")
            if said == state["number"]:
                state["digits"] += 1
                shown.configure(text=T("Right!"), foreground=GOOD)
                self.later(700, round_)
            else:
                done = state["digits"] - 1
                shown.configure(text=state["number"], foreground=FAINT)
                self.later(1500, lambda: self.over("number", done if done >= 4 else 0, T("You kept a number of {n} digits in mind.", n=done) if done >= 4 else T("It was {number}. Try once more?", number=state["number"]), self.number))

        field.bind("<Return>", answer)
        self.place()
        self.later(500, round_)

    # --- about your day
    def quiz(self) -> None:
        s = self.s
        status = self.head(T("About your day"))
        questions = day_questions(self.app)
        state = {"at": 0, "right": 0}
        asked = ttk.Label(self.frame, font=("Segoe UI Semibold", 11), wraplength=round(420 * s), justify="left")
        asked.pack(anchor="w", pady=(round(6 * s), round(8 * s)))
        box = ttk.Frame(self.frame)
        box.pack(fill="x")
        said = ttk.Label(self.frame, wraplength=round(420 * s), justify="left")
        said.pack(anchor="w", pady=(round(8 * s), 0))

        def show() -> None:
            for child in box.winfo_children():
                child.destroy()
            said.configure(text="")
            if state["at"] >= len(questions):
                self.over("quiz", state["right"], T("{n} of {of} right.", n=state["right"], of=len(questions)), self.quiz)
                return
            question, choices, right = questions[state["at"]]
            status.configure(text=T("Question {n} of {of}", n=state["at"] + 1, of=len(questions)))
            asked.configure(text=question)
            for choice in choices:
                ttk.Button(box, text=choice, command=lambda c=choice: pick(c, right)).pack(fill="x", pady=round(2 * s))
            self.place()

        def pick(choice: str, right: str) -> None:
            for child in box.winfo_children():
                child.configure(state="disabled")
            if choice == right:
                state["right"] += 1
                said.configure(text=T("Right!"), foreground=GOOD)
            else:
                said.configure(text=T("It was: {answer}", answer=right), foreground=FAINT)
            state["at"] += 1
            self.later(1100, show)

        show()


class Hunt:
    """One game of "Catch the mouse" on a whole screen."""

    PER_LEVEL = 6  # catches that make a level
    LIVES = 3

    def __init__(self, games: Games):
        from . import win32, world
        from .overlay import KEY, Overlay

        self.games, self.app = games, games.app
        app, s = self.app, games.s
        x, y = win32.cursor()
        monitors = win32.monitors()
        monitor = world.monitor_at(x, y, monitors) or (monitors[0] if monitors else None)
        self.area = area = monitor.rect if monitor else win32.Rect(0, 0, app.root.winfo_screenwidth(), app.root.winfo_screenheight())
        self.size = round(46 * s)  # the mouse, nose to tail root
        self.reach = self.size * 0.95  # a click this near its middle is a catch
        self.level, self.caught, self.lives = 1, 0, self.LIVES
        self.times: list = []
        self.spot = None  # where the mouse sits now (the middle of it, on the screen), or None
        self.shown = 0.0
        self.turn = 0
        self.after = None
        self.done = False

        # the dimmed screen: it takes the clicks and the Esc key
        veil = self.veil = tk.Toplevel(app.root)
        veil.overrideredirect(True)
        veil.configure(bg="#1E2130", cursor="hand2")
        veil.attributes("-alpha", 0.22)
        veil.attributes("-topmost", True)
        veil.geometry(f"{area.width}x{area.height}+{area.left}+{area.top}")
        veil.bind("<Button-1>", self.click)
        veil.bind("<Escape>", lambda e: self.stop())

        # the mouse: see-through around it, and no click stops at it (the veil below decides)
        side = self.size * 2
        self.sprite = Overlay(app.root, side, side)
        canvas = tk.Canvas(self.sprite, width=side, height=side, bg=KEY, highlightthickness=0, bd=0)
        canvas.pack()
        cx, cy, half = side // 2, side // 2, self.size // 2
        canvas.create_line(cx + half - 2, cy + 2, cx + self.size, cy - half // 2, fill=DARK, width=max(2, round(2 * s)))
        canvas.create_oval(cx - half, cy - half // 2, cx + half, cy + half // 2 + 2, fill=GREY, outline=DARK, width=max(1, round(s)))
        for dx in (-half // 2, half // 4):
            canvas.create_oval(cx + dx - half // 3, cy - half, cx + dx + half // 3, cy - half // 3, fill="#F2B8C6", outline=DARK)
        canvas.create_oval(cx - half + 4, cy - 3, cx - half + 8, cy + 1, fill=INK, outline="")
        win32.set_click_through(self.sprite.hwnd, True)

        # the bar at the top: a window that never takes the keyboard (Esc stays with the
        # dimmed screen) and is put back on top whenever a click raised the screen over it
        bar = self.bar = Overlay(app.root, 10, 10, see_through=False)
        bar.configure(bg=INK)
        inner = tk.Frame(bar, bg=CARD)
        inner.pack(padx=max(1, round(s)), pady=max(1, round(s)))
        self.status = tk.Label(inner, bg=CARD, fg=INK, font=("Segoe UI Semibold", 11), padx=round(14 * s), pady=round(7 * s))
        self.status.pack(side="left")
        tk.Label(inner, text=T("Click the mouse. Esc stops."), bg=CARD, fg=FAINT, font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(inner, text=T("Stop"), style="Chip.TButton", command=self.stop).pack(side="left", padx=round(12 * s), pady=round(4 * s))
        self.tell()
        bar.update_idletasks()
        width, height = bar.winfo_reqwidth(), bar.winfo_reqheight()
        bar.set_box(width, height, area.left + (area.width - width) // 2, area.top + round(18 * s))
        self.top = height + round(40 * s)  # the mouse keeps below the bar
        self.on_top = lambda: win32.keep_on_top(bar.hwnd) if bar.winfo_exists() else None

    def start(self) -> None:
        self.veil.lift()
        self.veil.focus_force()
        self.bar.set_visible(True)
        self.app.root.after(60, self.on_top)
        self.later(900, self.show)

    def later(self, ms: int, fn) -> None:
        self.after = self.app.root.after(ms, fn)

    def show_time(self) -> int:
        """How long the mouse stays, in ms: long enough to cross a screen at first, shorter with each level."""
        return max(520, round(2300 * 0.87 ** (self.level - 1)))

    def tell(self) -> None:
        self.status.configure(text=T("Level {level}   ·   caught {n} of {of}   ·   lives {lives}", level=self.level, n=self.caught, of=self.PER_LEVEL, lives="♥" * self.lives))

    def show(self) -> None:
        if self.done:
            return
        area, edge = self.area, self.size * 2
        x = random.randint(area.left + edge, max(area.left + edge, area.right - edge))
        y = random.randint(area.top + self.top + edge, max(area.top + self.top + edge, area.bottom - edge))
        self.sprite.move(x - self.size, y - self.size)
        self.sprite.set_visible(True)
        self.on_top()
        self.spot, self.shown = (x, y), time.monotonic()
        self.turn += 1
        mine = self.turn
        self.later(self.show_time(), lambda: self.missed(mine))

    def hide(self) -> None:
        self.spot = None
        self.sprite.set_visible(False)

    def missed(self, mine: int) -> None:
        if mine != self.turn or self.done:
            return
        self.hide()
        self.lives -= 1
        self.tell()
        if self.lives <= 0:
            self.stop()
        else:
            self.later(600, self.show)

    def click(self, event) -> None:
        """A click anywhere on the dimmed screen: a catch if it is on the mouse, nothing otherwise."""
        self.app.root.after(10, self.on_top)  # the click raised the dimmed screen: the bar goes back over it
        if self.spot is None or self.done:
            return
        x, y = self.area.left + event.x, self.area.top + event.y
        if (x - self.spot[0]) ** 2 + (y - self.spot[1]) ** 2 > self.reach ** 2:
            return
        self.times.append(time.monotonic() - self.shown)
        self.turn += 1
        self.hide()
        self.caught += 1
        if self.caught >= self.PER_LEVEL:
            self.level, self.caught = self.level + 1, 0
        self.tell()
        if self.after is not None:
            self.app.root.after_cancel(self.after)
        self.later(random.randint(400, 950), self.show)

    def stop(self) -> None:
        if self.done:
            return
        self.done = True
        if self.after is not None:
            try:
                self.app.root.after_cancel(self.after)
            except tk.TclError:
                pass
        for window in (self.sprite, self.bar, self.veil):
            if window.winfo_exists():
                window.destroy()
        if self.games.win.winfo_exists():
            self.games.hunt_over(self.level, self.times)


def _choices(right: str, others: list, most: int = 4) -> list:
    pool = [other for other in dict.fromkeys(others) if other != right][: most - 1]
    out = pool + [right]
    random.shuffle(out)
    return out


def day_questions(app, most: int = 5) -> list:
    """(question, choices, the right one) about the person's own yesterday, from what the
    cat has seen; filled up with sums where it has seen too little."""
    store = app.store
    out: list = []
    today = dt.date.fromisoformat(app.today)
    yesterday = today - dt.timedelta(days=1)
    start = int(dt.datetime.combine(yesterday, dt.time()).timestamp())
    end = start + 86400
    try:
        usage = store.usage(yesterday.isoformat(), yesterday.isoformat()).get(yesterday.isoformat(), {})
        names = {place: row.get("name") or place for place, row in store.places().items()}
        totals = sorted(((sum(slots.values()), names.get(place, place)) for place, slots in usage.items()), reverse=True)
        totals = [(seconds, name) for seconds, name in totals if seconds >= 60]
        if len(totals) >= 3:
            out.append((T("Which program or site did you spend the most time in yesterday?"), _choices(totals[0][1], [name for _s, name in totals[1:]]), totals[0][1]))
            hours = round(sum(seconds for seconds, _n in totals) / 3600)
            right = T("about {n} h", n=hours)
            out.append((T("How long were you at the computer yesterday?"), _choices(right, [T("about {n} h", n=max(0, hours + d)) for d in (-2, 2, 4, -1)]), right))
            if len(totals) >= 4:
                least = totals[-1][1]
                out.append((T("Which of these did you use the least yesterday?"), _choices(least, [name for _s, name in totals[:3]]), least))
        done = [task for task in store.finished(start) if (task.get("done") or 0) < end]
        right = str(len(done))
        out.append((T("How many tasks did you finish yesterday?"), _choices(right, [str(max(0, len(done) + d)) for d in (1, 2, -1, 3)]), right))
        if done:
            text = done[-1]["text"]
            decoys = [T("Clean the keyboard"), T("Call the dentist"), T("Back up the photos"), T("Renew the passport")]
            out.append((T("Which of these did you finish yesterday?"), _choices(text, decoys), text))
        tasks = [task["text"] for task in store.tasks()]
        if tasks:
            right = str(len(tasks))
            out.append((T("How many tasks are open on your list right now?"), _choices(right, [str(max(0, len(tasks) + d)) for d in (1, -1, 2, 3)]), right))
    except Exception:  # noqa: BLE001  (a game must never fail over what is in the diary)
        pass
    random.shuffle(out)
    out = out[:most]
    while len(out) < most:  # nothing seen yet: something for the head all the same
        a, b = random.randint(12, 49), random.randint(11, 39)
        right = str(a + b)
        out.append((T("And without a calculator: {a} + {b} = ?", a=a, b=b), _choices(right, [str(a + b + d) for d in (10, -10, 1, -2)]), right))
    return out


# --------------------------------------------------------------------------- habits and goals

SPANS = (("week", N_("This week")), ("month", N_("This month")), ("year", N_("This year")))


def period(span: str, day: dt.date) -> str:
    if span == "week":
        year, week, _weekday = day.isocalendar()
        return f"{year}-W{week:02d}"
    return day.strftime("%Y-%m") if span == "month" else str(day.year)


def streak(days: set, today: dt.date) -> int:
    """Days in a row up to today (or up to yesterday, while today is still open)."""
    day = today if today.isoformat() in days else today - dt.timedelta(days=1)
    count = 0
    while day.isoformat() in days:
        count += 1
        day -= dt.timedelta(days=1)
    return count


def current_goals(store, span: str, today: dt.date) -> list:
    """The goals of this week (month, year), and those of earlier ones that are not done yet."""
    now = period(span, today)
    return [goal for goal in store.long_goals(span) if goal["progress"] < 100 or goal["period"] == now]


_PERCENT = re.compile(r"(\d{1,3})\s*(?:%|percent|per cent|процент\w*|фоиз\w*|foiz\w*)", re.I)


def progress_wish(store, text: str, today: dt.date):
    """(goal, per cent) if this message says how far one of the person's goals is: it gives
    one percentage and names exactly one goal ("the report goal is at 70 %"). None
    otherwise, and for a question. Read from the person's own words: no model is asked."""
    found = _PERCENT.findall(text)
    if len(found) != 1 or int(found[0]) > 100 or text.rstrip().endswith(("?", "？")):
        return None
    said = assistant._stems(text) | assistant._stems(translit.to_latin(text))
    named = []
    for span, _title in SPANS:
        for goal in current_goals(store, span, today):
            if (assistant._stems(goal["text"]) | assistant._stems(translit.to_latin(goal["text"]))) & said:
                named.append(goal)
    return (named[0], int(found[0])) if len(named) == 1 else None


def goal_facts(store, today: dt.date) -> list:
    """Lines for the AI: the habits and how they are kept, the goals and how far each is."""
    lines = []
    habits = store.habits()
    if habits:
        day = today.isoformat()
        lines.append("Habits the user tracks (and whether each is done today): " + "; ".join(
            f"{habit['name']} ({'done' if day in store.habit_days(habit['id']) else 'not yet'})" for habit in habits[:12]) + ".")
    for span, _title in SPANS:
        goals = current_goals(store, span, today)
        if goals:
            lines.append(f"The user's goals for this {span} (with how far each is): " + "; ".join(f"{goal['text']} ({goal['progress']} %)" for goal in goals[:10]) + ".")
    return lines


class Goals:
    """Habits to tick off each day, and goals for the week, the month and the year."""

    def __init__(self, app):
        self.app = app
        self.s = app.ui_scale
        self.win, self.frame, self.place = _window(app, T("Habits and goals"))
        self.build()

    def build(self) -> None:
        for child in self.frame.winfo_children():
            child.destroy()
        app, s, store = self.app, self.s, self.app.store
        today = dt.date.fromisoformat(app.today)
        wrap = round(430 * s)

        ttk.Label(self.frame, text=T("Habits"), font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(self.frame, text=T("Small things for every day. Tick one when it is done; the dots are the last seven days."), style="Small.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(0, round(4 * s)))
        for habit in store.habits():
            days = store.habit_days(habit["id"])
            row = ttk.Frame(self.frame)
            row.pack(fill="x", pady=round(1 * s))
            ttk.Button(row, text=T("Delete"), style="Chip.TButton", command=lambda i=habit["id"]: self.change(store.delete_habit, i)).pack(side="right")
            run = streak(days, today)
            dots = "".join("●" if (today - dt.timedelta(days=back)).isoformat() in days else "○" for back in range(6, -1, -1))
            ttk.Label(row, text=dots + ("   " + T("{n} days in a row", n=run) if run >= 2 else ""), style="Small.TLabel").pack(side="right", padx=round(10 * s))
            var = tk.BooleanVar(value=today.isoformat() in days)
            ttk.Checkbutton(row, text=habit["name"], variable=var, command=lambda i=habit["id"], v=var: self.change(store.mark_habit, i, today.isoformat(), v.get())).pack(side="left")
        self.adder(T("A new habit, for example: read 20 minutes"), lambda text: store.add_habit(text))

        for span, title in SPANS:
            ttk.Separator(self.frame).pack(fill="x", pady=round(10 * s))
            now = period(span, today)
            goals = current_goals(store, span, today)
            average = round(sum(goal["progress"] for goal in goals) / len(goals)) if goals else 0
            ttk.Label(self.frame, text=T(title) + (f"   ·   {average} %" if goals else ""), font=("Segoe UI Semibold", 12)).pack(anchor="w")
            if goals:
                ttk.Label(self.frame, text=T("Type how far each one is, from 0 to 100, and press Enter."), style="Small.TLabel").pack(anchor="w")
            for goal in goals:
                row = ttk.Frame(self.frame)
                row.pack(fill="x", pady=round(2 * s))
                ttk.Button(row, text=T("Delete"), style="Chip.TButton", command=lambda i=goal["id"]: self.change(store.delete_long_goal, i)).pack(side="right")
                ttk.Label(row, text="%").pack(side="right", padx=(round(2 * s), round(8 * s)))
                var = tk.StringVar(value=str(goal["progress"]))
                field = ttk.Entry(row, textvariable=var, width=4, justify="right")
                field.pack(side="right")
                set_it = lambda _e=None, i=goal["id"], v=var: self.progress(i, v.get())  # noqa: E731
                field.bind("<Return>", set_it)
                field.bind("<FocusOut>", set_it)
                bar = tk.Canvas(row, width=round(90 * s), height=round(10 * s), bg=FIELD, highlightthickness=0)
                bar.pack(side="right", padx=round(8 * s))
                bar.create_rectangle(0, 0, round(90 * s * goal["progress"] / 100), round(10 * s), fill=GOOD if goal["progress"] >= 100 else AMBER, outline="")
                label = ("✓ " if goal["progress"] >= 100 else "") + goal["text"] + ("" if goal["period"] == now else "   (" + T("from before") + ")")
                ttk.Label(row, text=label, wraplength=round(230 * s), justify="left").pack(side="left")
            self.adder(T("A goal"), lambda text, span=span, now=now: store.add_long_goal(span, now, text))
        self.place()

    def adder(self, hint: str, add) -> None:
        s = self.s
        row = ttk.Frame(self.frame)
        row.pack(fill="x", pady=(round(4 * s), 0))
        var = tk.StringVar()
        field = ttk.Entry(row, textvariable=var, width=40)
        field.pack(side="left")

        def go(_event=None) -> None:
            text = " ".join(var.get().split())[:120]
            if text:
                add(text)
                self.build()

        field.bind("<Return>", go)
        ttk.Button(row, text=T("Add"), command=go).pack(side="left", padx=round(6 * s))
        ttk.Label(self.frame, text=hint, style="Small.TLabel").pack(anchor="w")

    def progress(self, goal: int, typed: str) -> None:
        digits = "".join(ch for ch in typed if ch.isdigit())
        known = self.app.store.long_goal(goal)
        if known is None or not digits or int(digits) == known["progress"]:
            return
        self.app.store.set_long_goal(goal, int(digits))
        self.win.after(10, self.build)

    def change(self, fn, *args) -> None:
        fn(*args)
        self.build()
