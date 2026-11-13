"""The app: wires the cat to the tracker, the timer, the brain and the windows.

Three loops run on Tk's own thread:

    fast    4 times a second   tray clicks, the focus clock, the speech queue
    sample  every 5 seconds    where you are, time accounting, mood, reminders that are due
    think   every 30 seconds   suggestions: breaks, routines, music, small talk

Helper threads only fetch things and put them into `inbox`: the tray icon, the "what is
playing" watcher and the offline AI. They never touch Tk or the database.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import logging.handlers
import os
import queue
import random
import re
import time
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path

from . import APP_NAME, INSTANCE, __version__, advisor, apps, assistant, autostart, brain, days, hotkeys, lines, media, mood, nudges, reader, tasks, translit, tray, weather, win32
from .ai import AI
from .bubble import Voice
from .focus import Focus
from .i18n import T, duration, plain, system_language
from .i18n import load as load_language
from .menu import Menu
from .overlay import Images
from .pet import Pet
from .quick import QuickBox
from .scene import Scene
from .sounds import Sounds
from .store import Store, adopt_old_folder, default_folder
from .tracker import Tracker, day_of, slot_label

log = logging.getLogger("workcat")

NUDGE_GAP = 20 * 60  # at most one unasked suggestion in this many seconds
LOOKBACK_DAYS = 35
WEEK = 7 * 86400
ENOUGH = 3  # this many refusals in a row and the cat stops suggesting that for a while
REST = 14 * 86400
TASKS_TOLD = 30  # this many open tasks at most are laid before the AI
BUBBLE_ROOM = (330, 7)  # an answer longer than this many letters or lines is cut short in the cat's bubble
# What the AI may do by itself, and the switch in the AI brain tab for each (see assistant.ABILITIES).
ABILITY_SWITCHES = (("add", "ai_may_add"), ("edit", "ai_may_edit"), ("timer", "ai_may_timer"), ("open", "ai_may_open"), ("memory", "ai_memory"))


def search_url(query: str) -> str:
    """The address of a web search, to open in the person's own browser."""
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


def clipped(text: str, letters: int, lines: int) -> tuple:
    """(text, was it cut): a long text shortened for the cat's bubble, at the end of a
    word, with "…" where it stops."""
    rows = text.split("\n")
    cut = len(rows) > lines
    short = "\n".join(rows[:lines])
    if len(short) > letters:
        cut = True
        short = short[:letters]
        short = short[: max(short.rfind(" "), short.rfind("\n"), letters // 2)]
    return (short.rstrip(" ,;:\n") + "…", True) if cut else (text, False)


def _drain(q: queue.Queue):
    while True:
        try:
            yield q.get_nowait()
        except queue.Empty:
            return


def _noop() -> None:
    pass


def midnight(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").timestamp())


def instance_name(folder) -> str:
    """What a running cat is known by to other programs. There is one cat for each data
    folder: a copy started with its own --data may run beside the usual one."""
    def same(path) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    if same(folder) == same(default_folder()):
        return INSTANCE
    return INSTANCE + "-" + hashlib.sha1(same(folder).encode("utf-8")).hexdigest()[:12]


class App:
    def __init__(self, folder=None, overrides=None):
        win32.set_dpi_awareness()
        win32.set_app_id("WorkCat.Desktop")
        self.store = Store(folder or default_folder())
        self.settings = self.store.settings
        if self.store.fresh:
            self.settings["language"] = system_language()  # start in the language Windows is in, if we have it
        if overrides:
            self.settings.update(overrides)
        load_language(self.settings.get("language", "en"))

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = lambda *error: log.error("tk callback", exc_info=error)
        self.ui_scale = win32.system_dpi() / 96.0
        try:
            # For looking at every window as a screen set to larger text shows it, on a
            # screen that is not:  set WORKCAT_UI_SCALE=1.5
            pretend = float(os.environ.get("WORKCAT_UI_SCALE") or 0)
        except ValueError:
            pretend = 0.0
        if 0.5 <= pretend <= 4:
            self.ui_scale = pretend
            self.root.tk.call("tk", "scaling", pretend * 96 / 72)
        size = self.settings["size"]
        self.scale = size if size in (1, 2, 3, 4) else max(2, round(2 * self.ui_scale))
        self.icon_path = tray.write_icon(self.store.folder / "workcat.ico", self.settings["coat"])
        try:
            self.root.iconbitmap(default=str(self.icon_path))
        except tk.TclError:
            pass

        self.images = Images(self.root, self.scale)
        self.scene = Scene()
        self.tracker = Tracker(self.store, learn=self.may("learn_routine"))
        self.focus = Focus()
        self.focus_len = self.settings["focus_min"]
        self.playlog = media.PlayLog(self.store)
        self.inbox: queue.Queue = queue.Queue()
        self.watcher = None
        self.quiet = ""
        self.in_call = False
        self.user_hidden = False
        self.hide_until = 0.0
        self.closing = False
        self.panel = None

        now = time.time()
        self.today = day_of(now)
        saved = self.store.get("said", {})
        self.said = set(saved.get("keys", [])) if saved.get("day") == self.today else set()
        started = self.store.get("day_start", {})
        self.day_started = started.get("ts") if started.get("day") == self.today else None
        self.pets_today = self.store.count("pet", midnight(self.today))
        self.last_pet = None
        self.last_win = None
        self.bond = int(self.store.get("bond", 0) or 0)
        self.condition = mood.Condition("content", T("All is well."), 80)
        self.noted = None
        self.last_nudge = now - NUDGE_GAP + 120  # a couple of quiet minutes after starting
        self.last_break_nudge = 0.0
        self.last_flush = now
        self.last_mic = 0.0
        self.next_chat = now + random.uniform(20, 40) * 60
        self.routine_cache = (0.0, [])
        self.rhythm_cache = (0.0, None)
        self.stretch_cache = (0.0, None)
        self.summary_cache = (0.0, "", None)

        self.ai = AI(self)
        self.ai.listeners.append(self.on_ai)
        self.ai_named: list = []  # names in what the AI was last told: see ai_names()
        self.chat_log: list = []  # the talk so far, for the Chat window: ("you" | "cat" | "error", text, notes)
        if self.settings["ai_keep_talk"]:  # what was said before the app was last closed
            self.chat_log = [("you" if row["role"] == "user" else "cat", row["shown"] or "", ()) for row in self.store.talk()]
        self.ask_source = "window"  # where the question being answered came from: the Chat "window", the ask "box", or a daily "script"
        self.script_now = None  # the daily script that is being run just now
        self.reading_said = False  # "Reading Telegram..." is in the cat's bubble
        self.last_idle = 0.0  # seconds since the keyboard or mouse was last touched, as of the last look
        self.sounds = Sounds(self.store.folder)
        if self.settings["sounds"]:
            self.sounds.prepare()
        self.last_play = None
        self.pounces = 0
        self.care_at = {"eyes": now, "water": now}  # when each small reminder last had its turn
        self.weather = weather.Weather(self)
        self.nudges = nudges.Nudges(self, now)  # what the cat brings up by itself: a task or a goal, meals, that it is late
        self.settings["autostart"] = autostart.enabled()  # Windows knows best: the installer may have switched it on
        self.pet = Pet(self)
        self.voice = Voice(self)
        self.menu = Menu(self)
        self.quick = QuickBox(self)
        self.tray = tray.Tray(self.icon_path, APP_NAME, hotkeys.merged(self.settings["hotkeys"]), name=instance_name(self.store.folder))
        self.tray.start()

        self.every(250, self.fast)
        self.every(5000, self.sample, first=800)
        self.every(30000, self.think, first=20000)
        if not self.settings["first_run_done"]:
            self.root.after(500, self.welcome)
        elif self.store.get("seen_version") != __version__:
            self.root.after(4000, self.whats_new)
        if self.settings["first_run_done"] and self.ai.interrupted():
            self.root.after(9000, self.resume_ai)
        if self.settings["first_run_done"] and self.ai.moved_to:
            self.root.after(15000, self.service_moved)
        if self.settings["first_run_done"]:
            self.root.after(6000, self.ai.find_model)  # an online AI with a key but no model picks one

    def service_moved(self) -> None:
        """The key that was saved belongs to another service than the one that was chosen
        with it: the choice was moved to the key's own service, and the cat says so."""
        if self.closing:
            return
        text = T("The key you saved is a key for {service}, so I switched the service to it.", service=T(self.ai.moved_to))
        self.voice.say(text, [(T("AI brain"), lambda: self.open_panel("brain")), (T("Got it"), _noop)], kind="nudge", ttl=30)

    def resume_ai(self) -> None:
        """The offline AI was still being fetched when the app was last closed (the
        computer was switched off, or the app was updated). It was asked for once, so the
        download goes on from where it stopped, and the cat says so."""
        if self.closing or not self.ai.interrupted():
            return
        self.ai.setup()
        self.voice.say(T("I am going on with the download of my AI brain, from where it stopped."), [(T("Got it"), _noop), (T("Stop"), self.ai.stop_setup)], kind="nudge", ttl=30)

    def whats_new(self) -> None:
        """Said once after an update, so new things are not left undiscovered."""
        seen = self.store.get("seen_version") or ""
        self.store.put("seen_version", __version__)
        if seen.startswith("0.10"):  # a corrected build of what is known already: nothing new to tell
            return
        if seen.startswith("0.9"):
            text = T("New: now and then I remind you by myself: of a task or a goal, of breakfast and lunch, that it is late, and in the morning of the weather and what day it is. Settings has a switch for each.")
            self.voice.say(text, [(T("Settings"), lambda: self.open_panel("settings")), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        if seen.startswith("0.8"):
            text = T('New: "Play with me" has games now (catch the mouse, memory, a quiz about your day), and my menu has "Habits and goals".')
            self.voice.say(text, [(T("Play with me"), self.play_with_cat), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        if seen.startswith("0.7"):
            text = T("New: if you allow it, I can read what another program shows, to answer a question about it or for a daily script. It is off until you switch it on in my AI brain tab.")
            self.voice.say(text, [(T("AI brain"), lambda: self.open_panel("brain")), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        if seen:  # whoever had an earlier version knows the program by its earlier name
            self.voice.say(T("This program is called {app} now. Look for it under that name in the Start menu.", app=APP_NAME), [(T("Got it"), _noop)], kind="nudge", ttl=25)
        if seen.startswith("0.6"):
            text = T('New: "Both" in my AI brain tab uses the online AI while there is a connection and the one on this computer when there is not. And you can give me daily scripts there.')
            self.voice.say(text, [(T("AI brain"), lambda: self.open_panel("brain")), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        if seen.startswith(("0.4", "0.5")):  # everything is known but what the AI learned to do
            text = T("I can do more now: finish and move your tasks, open programs, help with texts, remember what you tell me. My AI brain has its own tab.")
            self.voice.say(text, [(T("AI brain"), lambda: self.open_panel("brain")), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        if seen.startswith(("0.2", "0.3")):  # the look, the moods and the AI are known already
            text = T("I learned new things. Double-click me to talk. Drag me to the side of the screen to tuck me away. Settings has the rest: languages, shortcut keys, goals for your day.")
            self.voice.say(text, [(T("Settings"), lambda: self.open_panel("settings")), (T("Later"), _noop)], kind="nudge", emote="happy", ttl=40)
            return
        text = T('I have a new look and moods of my own now. Right-click me and try "What should I do now?".')
        if self.ai.state == "ready":
            text = T('I have a new look, moods of my own, and an AI brain that runs only on this PC. Right-click me and pick "Ask me".')
        self.voice.say(text, [(T("Ask me"), lambda: self.open_panel("chat"))], kind="nudge", emote="happy", ttl=30)

    def every(self, ms: int, fn, first: int = 0) -> None:
        """Run fn now and then forever, surviving its exceptions."""
        def run():
            if self.closing:
                return
            try:
                fn()
            except Exception:
                log.exception("loop %s", fn.__name__)
            self.root.after(ms, run)

        self.root.after(first or ms, run)

    def run(self) -> None:
        self.root.mainloop()

    def may(self, key: str) -> bool:
        """Whether a kind of learning is allowed. Nothing is, until the welcome screen
        has been answered: the choices there are made before anything is recorded."""
        return bool(self.settings["first_run_done"] and self.settings.get(key))

    # ------------------------------------------------------------------ the three loops

    def fast(self) -> None:
        for event in _drain(self.tray.events):
            if event == "click":
                self.tray_clicked()
            elif event == "menu":
                self.show_menu(*win32.cursor())
            elif event == "keys":
                self.keys_registered()
            elif event == "show":  # the app was started a second time
                self.come_back()
            elif event == "quit":  # the setup program is about to replace our files
                self.root.after(0, self.quit)
                return
            elif event.startswith("key:"):
                self.shortcut(event[4:])
        for kind, payload in _drain(self.inbox):
            if kind == "media":
                self.on_media(payload)
            elif kind == "ai":
                self.ai.handle(*payload)
            elif kind == "weather":
                self.weather.arrived(payload)
        now = time.time()
        ended = self.focus.tick(now)
        if ended:
            self.on_phase_end(ended)
        self.scene.focus = self.focus.progress(now) if self.focus.focusing else None
        self.scene.on_break = self.focus.on_break
        self.voice.pump()

    def sample(self) -> None:
        now = time.time()
        if day_of(now) != self.today:
            self.today = day_of(now)
            self.said = set()
            self.day_started = None
            self.pets_today = 0
            self.routine_cache = (0.0, [])
        self.quiet = win32.quiet_state()
        if now - self.last_mic >= 10:
            self.last_mic = now
            self.in_call = win32.mic_in_use()
        idle = win32.idle_seconds()
        away = self.quiet == win32.QUIET_AWAY
        self.last_idle = max(idle, 600.0) if away else idle
        happened = self.tracker.sample(now, idle, self.read_place(), away)
        place = self.tracker.place
        if self.day_started is None and idle < 60 and not away:
            self.day_started = now
            self.store.put("day_start", {"day": self.today, "ts": now})
        self.scene.category = self.tracker.category(place)
        self.scene.idle = max(idle, 600.0) if away else idle
        self.scene.in_call = self.in_call
        self.scene.music = self.playlog.playing
        open_tasks = self.store.tasks()
        self.condition = mood.condition(self.day_facts(now, open_tasks))
        self.scene.mood = self.condition.mood
        self.update_hidden(now)
        if happened.get("returned", 0) >= 30 * 60:
            self.pet.emote("yawn", 1.8)
            self.voice.say(T("Welcome back!"), kind="chat", emote="yawn")
        if happened.get("returned", 0) >= 120:
            self.care_at["eyes"] = now  # away from the screen for a while: the eyes have rested
        self.check_notes(now, open_tasks)
        self.check_tasks(now, open_tasks)
        self.greet_once(now, idle)
        if now - self.last_flush >= 60:
            self.last_flush = now
            self.tracker.flush()
        self.sync_watcher()

    def think(self) -> None:
        now = time.time()
        self.ai.rest(now)
        self.ai.watch()  # with "both" chosen: is the online AI still within reach?
        self.weather.tick(now)  # a fresh forecast every few hours, if that is switched on
        if not self.voice.busy() and self.scripts_due(now):
            return
        if self.voice.busy() or self.quiet_level() or self.scene.paused or self.focus.phase:
            return
        if self.break_due(now) or self.recap_due(now) or self.plan_due(now) or self.goals_due(now) or self.week_note_due(now) or self.care_due(now) or self.nudges.due(now):
            return
        if now - self.last_nudge >= NUDGE_GAP and (self.nudge_routine(now) or self.nudge_media(now)):
            self.last_nudge = now
            return
        self.small_talk(now)

    # ------------------------------------------------------------------ where you are

    def read_place(self):
        """The place in front right now; None while it is one of our own windows."""
        hwnd = win32.foreground()
        if not hwnd or win32.pid_of(hwnd) == os.getpid():
            return None
        _pid, path = win32.app_of_window(hwnd)
        if not path:
            return None
        title = ""
        if self.may("learn_sites") and apps.stem_of(path) in apps.BROWSERS:
            title = win32.window_title(hwnd)  # compared with the site list, then dropped
        return apps.identify(path, win32.file_description(path), title)

    def quiet_level(self) -> str:
        """'hard': show nothing. 'soft': only reminders you asked for. '': anything."""
        if self.pet.hidden or self.quiet:
            return "hard"
        if self.focus.focusing or self.pet.tucked or (self.in_call and self.settings["quiet_in_calls"]):
            return "soft"
        return ""

    def update_hidden(self, now: float) -> None:
        busy_screen = self.settings["hide_in_fullscreen"] and self.quiet in (win32.QUIET_FULLSCREEN, win32.QUIET_PRESENTING)
        hidden = self.user_hidden or now < self.hide_until or busy_screen
        if hidden != self.pet.hidden:
            if hidden:
                self.voice.hush()
                self.menu.close()
            self.pet.set_hidden(hidden)

    def toggle_hidden(self) -> None:
        """The show-or-hide key: bring the cat back if it is hidden or tucked away, else hide it."""
        if self.pet.hidden:
            self.user_hidden = False
            self.hide_until = 0.0
        elif self.pet.tucked:
            self.untuck()
            return
        else:
            self.user_hidden = True
            self.quick.close()
        self.update_hidden(time.time())

    def hide_for(self, minutes: int) -> None:
        self.hide_until = time.time() + minutes * 60
        self.update_hidden(time.time())

    def tray_clicked(self) -> None:
        """A click on the icon near the clock brings a hidden cat back; otherwise it opens the window."""
        if self.pet.hidden or self.pet.tucked:
            self.toggle_hidden()
        else:
            self.open_panel()

    def come_back(self) -> None:
        """The app was started again while it is running (its shortcut on the desktop,
        the Start menu): whoever did that wants to see the cat, so it comes out and
        opens its window."""
        if not self.settings["first_run_done"]:
            return  # the welcome window is still waiting for its answer
        if self.pet.hidden or self.pet.tucked:
            self.toggle_hidden()
        self.open_panel()

    def keys_registered(self) -> None:
        """Windows has been told our shortcut keys. A usual key that another program
        already holds is swapped for a spare one, and that is remembered. Keys the person
        chose are theirs: if those are taken, Settings says so and changes nothing."""
        chosen = self.settings["hotkeys"]
        saved = dict(chosen) if isinstance(chosen, dict) else {}
        keys = hotkeys.merged(saved)
        swapped = False
        for name in sorted(self.tray.taken):
            other = "" if name in saved else hotkeys.spare(name, keys, tray.free)
            if other:
                log.info("%s is held by another program: using %s", keys[name], other)
                saved[name] = keys[name] = other
                swapped = True
        if swapped:
            self.settings["hotkeys"] = saved
            self.store.save_settings()
            self.tray.set_shortcuts(keys)  # 'keys' comes again once they are registered
        self.refresh_panel()

    def shortcut(self, name: str) -> None:
        """A shortcut key was pressed, in whatever program you were in."""
        if name == "toggle":
            self.toggle_hidden()
        elif name == "ask":
            self.quick_ask()
        elif name == "task":
            self.quick_task()
        elif name == "focus":
            if self.focus.focusing:
                self.stop_focus()
            else:
                self.start_focus()

    # ------------------------------------------------------------------ tucked away at the side of the screen

    def on_tucked(self, where) -> None:
        """The cat was tucked away (`where` says where) or came out again (None)."""
        self.settings["tucked"] = where or {}
        self.store.save_settings()
        if where:
            self.voice.hush()
            self.menu.close()
            self.quick.close()
            if not self.store.get("tuck_told"):
                self.store.put("tuck_told", True)
                self.voice.say(T("I will wait here. Click me when you want me back."), kind="reply", ttl=6)

    def untuck(self) -> None:
        self.pet.untuck()
        self.on_tucked(None)

    # ------------------------------------------------------------------ play and sounds

    def sound(self, name: str) -> None:
        if self.settings["sounds"] and self.quiet_level() != "hard":
            self.sounds.play(name)

    def play_with_cat(self) -> None:
        """The list of games."""
        if self.focus.focusing:
            self.voice.say(T("After the focus round!"), kind="reply", ttl=4)
            return
        from .extras import Games

        self.voice.hush()
        self.menu.close()
        old = getattr(self, "games", None)
        if old is not None and old.win.winfo_exists():
            old.win.destroy()
        self.games = Games(self)

    def open_goals(self) -> None:
        from .extras import Goals

        self.menu.close()
        old = getattr(self, "goals_window", None)
        if old is not None and old.win.winfo_exists():
            old.win.destroy()
        self.goals_window = Goals(self)

    def chase_pointer(self) -> None:
        if self.focus.focusing:
            self.voice.say(T("After the focus round!"), kind="reply", ttl=4)
            return
        if self.pet.hidden or self.pet.tucked:
            self.toggle_hidden()
        self.voice.hush()
        self.quick.close()
        self.pounces = 0
        self.pet.start_play(10.0)
        self.voice.say(T("Move the mouse. I will catch it!"), kind="reply", ttl=3, emote="cheer")

    def on_pounce(self) -> None:
        self.pounces += 1

    def on_play_over(self) -> None:
        now = time.time()
        self.last_play = now
        self.store.log("play", {"pounces": self.pounces}, ts=now)
        if self.pounces and self.store.count("play", midnight(self.today)) <= 3:
            self.add_bond(1)  # a few games a day bring you closer; more are just for fun
        text = T("Catches: {n}. That was fun!", n=self.pounces) if self.pounces else T("That was fun!")
        self.voice.say(text, kind="reply", ttl=5, emote="happy")

    # ------------------------------------------------------------------ mood and bond

    def day_facts(self, now: float, open_tasks=None) -> mood.Day:
        """Today as the mood rules need it."""
        clock = dt.datetime.fromtimestamp(now)
        day = self.today_summary(now)
        rhythm = self.rhythm(now)
        open_tasks = self.store.tasks() if open_tasks is None else open_tasks
        return mood.Day(
            hour=clock.hour + clock.minute / 60,
            weekend=clock.weekday() >= 5,
            active_s=day["active"],
            streak_s=self.tracker.streak,
            idle_s=self.scene.idle,
            focusing=self.focus.focusing,
            on_break=self.focus.on_break,
            focus_count=day["focus_count"],
            breaks=day["breaks"],
            tasks_done=day["done"],
            tasks_late=sum(1 for t in open_tasks if t["due"] and not t["place"] and t["due"] < now),
            pets=self.pets_today,
            since_pet=None if self.last_pet is None else now - self.last_pet,
            since_play=None if self.last_play is None else now - self.last_play,
            since_win=None if self.last_win is None else now - self.last_win,
            music=self.playlog.playing,
            usual_end=None if rhythm is None else rhythm[1] / 4,
            since_start=None if self.day_started is None else now - self.day_started,
            break_after_s=self.break_after_s(now) or 50 * 60,
        )

    def add_bond(self, points: int) -> None:
        before = mood.bond_level(self.bond)
        self.bond += points
        self.store.put("bond", self.bond)
        if mood.bond_level(self.bond) > before:
            self.voice.say(T("We are {level} now.", level=mood.bond_name(self.bond).lower()), kind="chat", emote="happy")

    def win(self, points: int) -> None:
        """Something got done: the cat is proud for a while and the bond grows."""
        self.last_win = time.time()
        self.add_bond(points)

    # ------------------------------------------------------------------ remembering what was said

    def clock(self) -> float:
        """Now, in seconds. (Asked here by what plans ahead, so that a test can set the hour.)"""
        return time.time()

    def city_unknown(self, city: str) -> None:
        """The weather service knows no place by the name that was typed: say so."""
        self.voice.say(
            T('I could not find a city called "{city}" for the weather. Try another spelling in Settings.', city=city),
            [(T("Settings"), lambda: self.open_panel("settings")), (T("Later"), lambda: None)], kind="nudge", ttl=25,
        )

    def say_once(self, key: str) -> bool:
        """True the first time a key is used today."""
        if key in self.said:
            return False
        self.said.add(key)
        self.store.put("said", {"day": self.today, "keys": sorted(self.said)})
        return True

    def offer(self, key: str, text: str, yes: tuple, no: str, never: bool = True, emote: str = "") -> None:
        """A suggestion the cat learns from. What you answer is remembered: say no three
        times running and it stops suggesting that for two weeks, without being told to."""
        answered = []

        def accept():
            answered.append(True)
            self.store.answer(key, True)
            yes[1]()

        def refuse():
            answered.append(False)
            self.refused(key, said_no=True)

        def never_again():
            answered.append(False)
            self.store.mute(key)

        def closed():
            if not answered:  # it went away unanswered
                self.refused(key, said_no=False)

        buttons = [(yes[0], accept), (no, refuse)]
        if never:
            buttons.append((T("Don't suggest"), never_again))
        self.voice.say(text, buttons, kind="nudge", emote=emote, on_close=closed)

    def refused(self, key: str, said_no: bool) -> None:
        record = self.store.answer(key, False)
        if record["streak"] >= (ENOUGH if said_no else ENOUGH + 2) and not self.store.muted(key):
            self.store.mute(key, int(time.time()) + REST)
            self.store.log("gave_up", {"key": key})
            if said_no:
                self.voice.say(T("Understood. I will leave that for a couple of weeks."), kind="reply", ttl=6)

    # ------------------------------------------------------------------ reminders

    def check_notes(self, now: float, open_tasks) -> None:
        """Notes left for a place ("remind me here") show a few seconds after arriving."""
        place = self.tracker.place
        if place is None or self.scene.paused:
            return
        since = self.tracker.place_since
        if now - since < 4 or self.noted == (place.id, since):
            return
        self.noted = (place.id, since)
        for note in tasks.notes_for(open_tasks, place.id, now)[:1]:
            self.store.update_task(note["id"], shown=int(now), tries=note["tries"] + 1)
            done = lambda task_id=note["id"]: self.complete_task(task_id)
            if note["repeat"]:
                buttons = [(T("Got it"), _noop), (T("Stop reminding"), done)]
            else:
                buttons = [(T("Done"), done), (T("Later"), _noop)]
            self.voice.say(T("{place}: {text}", place=place.name, text=note["text"]), buttons, ttl=35, kind="alert")
            self.sound("mew")

    def check_tasks(self, now: float, open_tasks) -> None:
        for task in tasks.due_tasks(open_tasks, now)[:1]:
            task_id = task["id"]
            self.store.update_task(task_id, shown=int(now), tries=task["tries"] + 1)
            self.voice.say(
                T("Reminder: {text}", text=task["text"]),
                [
                    (T("Done"), lambda i=task_id: self.complete_task(i)),
                    (T("In 10 min"), lambda i=task_id: self.store.update_task(i, due=int(time.time()) + 600, shown=None, tries=0)),
                    (T("Open tasks"), lambda: self.open_panel("tasks")),
                ],
                ttl=45,
                kind="alert",
            )
            self.sound("mew")

    def complete_task(self, task_id: int) -> None:
        self.store.update_task(task_id, done=int(time.time()))
        self.pet.emote("cheer", 1.6)
        self.summary_cache = (0.0, "", None)
        self.win(1)
        self.refresh_panel()

    def add_task_from_text(self, text: str) -> None:
        what, when = tasks.parse_quick(text, dt.datetime.now())
        if not what:
            return
        self.store.add_task(what, due=int(when.timestamp()) if when else None)
        if when:
            label = tasks.due_label(int(when.timestamp()), dt.datetime.now())
            self.voice.say(T("Got it. I'll remind you: {when}.", when=label), kind="reply", ttl=6)
        else:
            self.voice.say(T("Added to your list."), kind="reply", ttl=5)
        self.refresh_panel()

    def greet_once(self, now: float, idle: float) -> None:
        """The first time you are at the keyboard each day: hello, and yesterday in a line."""
        t = dt.datetime.fromtimestamp(now)
        if idle >= 60 or t.hour < 5 or not self.settings["first_run_done"] or self.store.get("greeted") == self.today:
            return
        if self.quiet_level() == "hard":
            return
        self.store.put("greeted", self.today)
        self.add_bond(3)  # another day together
        parts = [lines.greeting(t.hour, self.settings["name"])]
        yesterday = (t.date() - dt.timedelta(days=1)).isoformat()
        past = self.summary(yesterday)
        if past["active"] >= 600:
            text = T("Yesterday: {time} at the computer", time=duration(past["active"]))
            if past["focus_count"]:
                text += T(", {n} focus sessions", n=past["focus_count"])
            parts.append(text + ".")
        waiting = len(self.store.tasks())
        if waiting:
            parts.append(T("{n} on your list today.", n=waiting))
        self.voice.say(" ".join(parts), [(T("Open Today"), lambda: self.open_panel("today"))] if len(parts) > 1 else (), kind="nudge")

    # ------------------------------------------------------------------ your day: goals, recap, the week, small reminders

    def goals_today(self) -> list:
        return self.store.goals(self.today)

    def plan_due(self, now: float) -> bool:
        """Once in the morning, when there is an AI to do it: offer a plan for the day.
        It takes the place of the question about the three goals: one morning question,
        not two. Three "not today" in a row and it rests for two weeks, like the others."""
        clock = dt.datetime.fromtimestamp(now)
        if not self.settings["plan_morning"] or self.ai.state != "ready" or self.ai.busy or not 5 <= clock.hour < 13 or self.store.muted("plan", now):
            return False
        if self.day_started is None or now - self.day_started < 120 or "plan" in self.said or "goals" in self.said:
            return False
        self.say_once("plan")
        self.say_once("goals")
        self.offer("plan", T("Good morning! Shall I plan your day?"), (T("Plan my day"), self.plan_day), T("Not today"), emote="happy")
        return True

    def plan_day(self) -> None:
        """Ask the AI for a plan of the day, in the Chat window, where it can be read in
        full and changed by answering."""
        self.open_panel("chat")
        self.panel.send_chat(T("Plan my day: put my open tasks and goals in a sensible order for today."))

    # ------------------------------------------------------------------ daily scripts

    def scripts_due(self, now: float) -> bool:
        """A daily script whose time has come is run: one at a time, and when the person
        is there to see what comes of it. It waits while they are away, in a call, in a
        focus round or in something full screen. If the computer was off at its time, it
        runs once, later that day."""
        if self.script_now is not None or self.ai.busy or not self.settings["first_run_done"] or self.last_idle >= 120:
            return False
        if self.quiet_level() == "hard" or self.focus.focusing or (self.in_call and self.settings["quiet_in_calls"]):
            return False
        clock = dt.datetime.fromtimestamp(now)
        minute, weekday = clock.hour * 60 + clock.minute, clock.weekday()
        for script in self.store.scripts():
            if script["enabled"] and script["last"] != self.today and (script["days"] >> weekday) & 1 and minute >= script["at"]:
                return self.run_script(script)
        return False

    def run_script(self, script: dict, by_hand: bool = False) -> bool:
        """Hand a script to the AI. `by_hand`: the person pressed "Run now" (that does not
        count as today's run). True if it was started."""
        name = script["name"]
        if self.ai.state != "ready":
            if by_hand or self.say_once(f"script:{script['id']}:no-ai"):  # said once a day; it runs as soon as there is an AI
                self.voice.say(T('I could not run "{name}": my AI brain is not ready.', name=name), [(T("AI brain"), lambda: self.open_panel("brain"))], kind="alert", ttl=20)
            return False
        if self.ai.busy or self.script_now is not None:
            if by_hand:
                self.voice.say(T("One moment, I am still answering."), kind="reply", ttl=4)
            return False
        look = 0
        if script.get("look"):  # it starts by reading what a program shows
            program = script["look"]
            title = self.read_name(program)
            problem = ""
            if not self.may_read(program):
                problem = T('I could not run "{script}": I may not read {name}. That is switched off in my AI brain tab.', script=name, name=title)
            else:
                look = reader.window_of(program)
                if not look:
                    problem = T('"{script}" waits: {name} is not open on the screen, so I cannot look at it. I run it when it is.', script=name, name=title)
            if problem:
                if by_hand or self.say_once(f"script:{script['id']}:no-look"):  # said once a day
                    self.voice.say(problem, [(T("AI brain"), lambda: self.open_panel("brain"))], kind="alert", ttl=20)
                return False
        if not by_hand:
            self.store.update_script(script["id"], last=self.today)
        self.script_now = script
        if not self.ask_ai(script["text"], "script", look=look):
            self.script_now = None
            return False
        self.refresh_panel()
        return True

    def read_name(self, program: str) -> str:
        """A program that may be read, as people call it."""
        return self.settings["ai_read_names"].get(program) or apps.pretty_name(program)

    def may_read(self, program: str) -> bool:
        """Whether the person allowed the cat to read what this program shows."""
        s = self.settings
        return bool(s["first_run_done"] and s["ai_may_read"] and program and program in s["ai_read_programs"])

    def readable_now(self):
        """(window, program, name) of the program the person is working in, if the cat may
        read it; None otherwise."""
        if not self.settings["ai_may_read"]:
            return None
        win = win32.active_window(os.getpid())
        # (The cat's own menu may be in front at this moment: then it is the window the cat sits on.)
        hwnd = win.hwnd if win is not None else getattr(self.pet.seat, "hwnd", 0) or 0
        if not hwnd:
            return None
        program, name = reader.identity(hwnd)
        return (hwnd, program, name) if self.may_read(program) else None

    def asks_first(self) -> bool:
        """Whether what the AI wants done waits for a click: when that is switched on for
        everything, and during a daily script that may not act by itself."""
        return bool(self.settings["ai_ask_first"] or (self.script_now is not None and not self.script_now["acts"]))

    def goals_due(self, now: float) -> bool:
        """Once in the morning: ask for the three things that matter today."""
        clock = dt.datetime.fromtimestamp(now)
        if not self.settings["goals_ask"] or not 5 <= clock.hour < 13 or self.store.muted("goals", now):
            return False
        if self.day_started is None or now - self.day_started < 120 or self.goals_today() or not self.say_once("goals"):
            return False
        self.offer("goals", T("What are your three things for today?"), (T("Set goals"), self.ask_goals), T("Not today"))
        return True

    def ask_goals(self) -> None:
        self.voice.hush()
        self.menu.close()
        self.quick.show(T("Up to three, with a comma between them. Enter saves."), self.set_goals)

    def set_goals(self, text: str) -> None:
        """The goals for today, as typed. Goals set earlier today that are still open stop
        being goals (they stay on the list as ordinary tasks)."""
        wanted = [part.strip() for part in re.split(r"[;,\n]+", text) if part.strip()][:3]
        if not wanted:
            return
        self.make_goals(wanted)
        self.voice.say(T("Goals for today: {n}. I will keep them in view.", n=len(wanted)), kind="reply", ttl=6, emote="happy")
        self.refresh_panel()

    def make_goals(self, wanted: list, reuse: bool = False):
        """Make these the goals for today. With `reuse`, a goal that names a task already
        on the list makes that task the goal instead of a second copy of it. Returns a
        function that puts everything back as it was."""
        dropped = [goal["id"] for goal in self.goals_today() if not goal["done"]]
        for task_id in dropped:
            self.store.update_task(task_id, goal=None)
        clock = dt.datetime.now()
        added, marked = [], []
        waiting = [task for task in self.store.tasks() if not task["place"]] if reuse else []
        for part in wanted:
            what, when = tasks.parse_quick(part, clock)
            same = next((task for task in waiting if task["id"] not in marked and assistant.same_thing(what or part, task["text"])), None)
            if same:
                marked.append(same["id"])
                self.store.update_task(same["id"], goal=self.today)
            else:
                added.append(self.store.add_task(what or part, due=int(when.timestamp()) if when else None, goal=self.today))
        self.say_once("goals")

        def undo() -> None:
            for task_id in added:
                self.store.delete_task(task_id)
            for task_id in marked:
                self.store.update_task(task_id, goal=None)
            for task_id in dropped:
                self.store.update_task(task_id, goal=self.today)
            self.refresh_panel()

        return undo

    def recap_text(self, now: float) -> str:
        day = self.today_summary(now)
        parts = [T("Today: {time} at the computer. Focus rounds: {f}. Tasks done: {t}.", time=duration(day["active"]), f=day["focus_count"], t=day["done"])]
        goals = self.goals_today()
        if goals:
            parts.append(T("Goals: {a} of {b}.", a=sum(1 for goal in goals if goal["done"]), b=len(goals)))
        left = sum(1 for task in self.store.tasks() if not task["place"])
        if left:
            parts.append(T("Left for tomorrow: {n}.", n=left))
        return " ".join(parts)

    def recap_due(self, now: float) -> bool:
        """Once, around the time you usually finish (or at six): the day in a few numbers."""
        if not self.settings["recap"]:
            return False
        clock = dt.datetime.fromtimestamp(now)
        rhythm = self.rhythm(now)
        usual_end = rhythm[1] / 4 if rhythm else 18.0
        if clock.hour + clock.minute / 60 < usual_end - 0.25 or self.today_summary(now)["active"] < 2 * 3600 or not self.say_once("recap"):
            return False
        self.voice.say(self.recap_text(now), [(T("Open Today"), lambda: self.open_panel("today")), (T("Thanks"), _noop)], kind="nudge", ttl=40, emote="happy")
        return True

    def week(self, back: int = 0) -> dict:
        """A week in numbers, Monday to Sunday. back=1 is last week."""
        monday = dt.date.fromisoformat(brain.week_of(self.today)[0]) - dt.timedelta(days=7 * back)
        days = [(monday + dt.timedelta(days=i)).isoformat() for i in range(7)]
        known = self.store.places()
        usage = self.tracker.usage(days[0], days[-1])
        per_day = brain.per_day(usage, days)
        rows = [((known.get(place) or {}).get("name") or place, seconds, (known.get(place) or {}).get("category") or "other") for place, seconds in brain.totals(usage, days).items()]
        rows.sort(key=lambda row: -row[1])
        start, end = midnight(days[0]), midnight(days[-1]) + 86400
        sessions = self.store.events("focus_done", start, end)
        return dict(
            days=days,
            per_day=per_day,
            active=sum(per_day),
            places=rows,
            focus_count=len(sessions),
            focus_min=sum((data or {}).get("minutes", 0) for _, data in sessions),
            breaks=self.store.count("break", start, end) + self.store.count("break_start", start, end),
            done=self.store.done_between(start, end),
        )

    def week_note_due(self, now: float) -> bool:
        """Once a week: last week in a line, with a way to the weekly report."""
        this_week = brain.week_of(self.today)[0]
        if not self.settings["week_note"] or self.store.get("week_note") == this_week:
            return False
        self.store.put("week_note", this_week)  # one look a week, whether or not there is something to say
        last = self.week(1)
        if sum(1 for seconds in last["per_day"] if seconds >= 1800) < 2:
            return False
        longest = max(range(7), key=lambda i: last["per_day"][i])
        text = T("Last week: {time} at the computer. Focus rounds: {f}. Tasks done: {t}. Longest day: {day}.", time=duration(last["active"]), f=last["focus_count"], t=last["done"], day=T(tasks.WEEKDAYS[longest]))
        self.voice.say(text, [(T("See the week"), lambda: self.open_panel("week")), (T("Thanks"), _noop)], kind="nudge", ttl=40)
        return True

    def care_due(self, now: float) -> bool:
        """The two small reminders you can switch on: rest your eyes, drink some water."""
        for key, setting, text in (
            ("eyes", "eye_rest_min", T("Time to rest your eyes: look at something far away for twenty seconds.")),
            ("water", "water_min", T("A sip of water?")),
        ):
            every = int(self.settings[setting] or 0)
            if every and now - self.care_at[key] >= every * 60:
                self.care_at[key] = now
                self.voice.say(text, [(T("Done"), _noop), (T("Not now"), _noop)], kind="nudge", ttl=25)
                return True
        return False

    # ------------------------------------------------------------------ focus and breaks

    def start_focus(self, minutes=None) -> None:
        now = time.time()
        self.focus_len = int(minutes or self.settings["focus_min"])
        self.focus.start(now, self.focus_len)
        self.store.log("focus_start", {"minutes": self.focus_len}, ts=now)
        self.voice.hush()
        offer = self.focus_music(now)
        if offer:
            self.voice.say(
                T("Focus: {n} min. You often focus with {who}. Play it?", n=self.focus_len, who=offer["who"]),
                [(self.play_label(offer), lambda: self.play(offer)), (T("No music"), _noop)],
                kind="reply",
                ttl=14,
            )
        else:
            self.voice.say(T("Focus: {n} min. I'll keep quiet.", n=self.focus_len), kind="reply", ttl=5)
        self.refresh_panel()

    def stop_focus(self) -> None:
        now = time.time()
        if not self.focus.focusing:
            return
        ran = self.focus.minutes_run(now)
        self.focus.stop()
        if ran >= 5:
            self.store.log("focus_done", {"minutes": ran, "stopped": True}, ts=now)
            self.summary_cache = (0.0, "", None)
        self.voice.say(T("Stopped after {n} min.", n=ran), kind="reply", ttl=5)
        self.refresh_panel()

    def start_break(self) -> None:
        now = time.time()
        minutes = self.settings["break_min"]
        self.focus.start_break(now, minutes)
        self.tracker.streak = 0.0
        self.store.log("break_start", ts=now)
        self.summary_cache = (0.0, "", None)
        self.voice.say(T("Break: {n} min. Stand up, look out of a window.", n=minutes), kind="reply", ttl=6)
        self.refresh_panel()

    def end_break(self) -> None:
        self.focus.stop()
        self.refresh_panel()

    def on_phase_end(self, ended: str) -> None:
        if ended == "focus_done":
            self.store.log("focus_done", {"minutes": self.focus_len})
            self.summary_cache = (0.0, "", None)
            self.win(2)
            self.pet.emote("cheer", 2.6)
            self.voice.say(
                T("{n} minutes of focus done. Nice work! Take {b}?", n=self.focus_len, b=self.settings["break_min"]),
                [(T("Take a break"), self.start_break), (T("Keep going"), self.start_focus), (T("Done for now"), _noop)],
                ttl=45,
                kind="alert",
                emote="cheer",
            )
        else:
            self.voice.say(
                T("Break is over. Another round?"),
                [(T("Start focus"), self.start_focus), (T("Later"), _noop)],
                ttl=30,
                kind="alert",
            )
        self.refresh_panel()

    def break_after_s(self, now: float) -> float:
        """Seconds of work after which a stretch is suggested: your setting, brought
        forward if you usually pause sooner by yourself."""
        stamp, stretch = self.stretch_cache
        if now - stamp > 600:
            lengths = [(data or {}).get("after", 0) for _, data in self.store.events("break", int(now - 60 * 86400))]
            stretch = brain.own_stretch(lengths)
            self.stretch_cache = (now, stretch)
        return brain.break_after(self.settings["break_after_min"], stretch, bool(self.settings["adaptive_breaks"]))

    def break_due(self, now: float) -> bool:
        after = self.break_after_s(now)
        if not after or self.tracker.streak < after or now - self.last_break_nudge < 15 * 60:
            return False
        self.last_break_nudge = now
        minutes = int(self.tracker.streak // 60)
        text = T("You have been at it for {n} minutes. Stretch a little?", n=minutes)
        if after < self.settings["break_after_min"] * 60:  # the reminder came early because of your own rhythm
            usual = int(round(after / brain.EARLY / 60))
            text = T("You usually take a breather after about {usual} minutes. It has been {n}.", usual=usual, n=minutes)
        self.voice.say(text, [(T("{n}-min break", n=self.settings["break_min"]), self.start_break), (T("Later"), _noop)], kind="nudge", emote="yawn")
        return True

    # ------------------------------------------------------------------ what it learned: routines

    def history(self, now: float) -> tuple:
        """(usage of the last weeks, the days comparable with today)."""
        first = (dt.date.fromisoformat(self.today) - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
        usage = self.tracker.usage(first, self.today)
        return usage, brain.comparable_days(usage, self.today)

    def routines(self, now: float) -> list:
        stamp, found = self.routine_cache
        if now - stamp < 15 * 60:
            return found
        usage, days = self.history(now)
        skip = {place for place, row in self.store.places().items() if row["category"] in ("system", "browser")}
        found = brain.find_routines(usage, days, skip=skip)
        self.routine_cache = (now, found)
        return found

    def rhythm(self, now: float):
        """(usual first slot, usual last slot) of your day, or None while unknown."""
        stamp, hours = self.rhythm_cache
        if now - stamp > 15 * 60:
            usage, days = self.history(now)
            hours = brain.typical_hours(usage, days) if self.may("learn_routine") else None
            self.rhythm_cache = (now, hours)
        return hours

    def due_routines(self, now: float) -> list:
        """(routine, its place's row) for routines whose time is now and that you may be reminded of."""
        if not self.may("learn_routine"):
            return []
        t = dt.datetime.fromtimestamp(now)
        recent = self.tracker.recent_places(now)
        if self.tracker.place:
            recent.add(self.tracker.place.id)
        known = self.store.places()
        out = []
        for routine in brain.due_routines(self.routines(now), t.hour * 60 + t.minute, recent):
            row = known.get(routine.place)
            if row and not self.store.muted("routine:" + routine.place, now):
                out.append((routine, row))
        return out

    def nudge_routine(self, now: float) -> bool:
        for routine, row in self.due_routines(now):
            key = "routine:" + routine.place
            if not self.say_once(f"{key}:{routine.slot // 4}"):
                continue
            self.store.log("nudge", {"routine": routine.place}, ts=now)
            self.offer(
                key,
                T("You usually open {name} around {time}. Open it now?", name=row["name"], time=slot_label(routine.slot)),
                (T("Open"), lambda r=row: self.open_place(r)),
                T("Not today"),
            )
            return True
        return False

    def open_place(self, row: dict) -> None:
        site = apps.SITE_BY_KEY.get(row["place"])
        try:
            if site:
                if site.url:
                    webbrowser.open(site.url)
                return
            path = row.get("path") or ""
            hwnd = win32.window_of_exe(path) if path else 0
            if hwnd and win32.bring_to_front(hwnd):
                return
            if path and os.path.exists(path):
                os.startfile(path)
                return
        except OSError:
            log.info("could not open %s", row.get("place"))
        self.voice.say(T("I couldn't open {name} from here.", name=row.get("name") or row["place"]), kind="reply", ttl=6)

    # ------------------------------------------------------------------ what it learned: music and video

    def sync_watcher(self) -> None:
        want = self.may("learn_media")
        if want and self.watcher is None:
            self.watcher = media.MediaWatcher(self.inbox)
            self.watcher.start()
        elif not want and self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
            self.playlog.close()
            self.scene.music = False

    def on_media(self, playing) -> None:
        if self.may("learn_media"):
            self.playlog.update(time.time(), playing)
            self.scene.music = self.playlog.playing

    def play_label(self, play: dict) -> str:
        return T("Open in Spotify") if "spotify" in (play.get("app") or "").lower() else T("Find on YouTube")

    def play(self, play: dict) -> None:
        """Open a search for it where you usually play it: nothing starts on its own."""
        query = play["who"] if play.get("artist") else (play.get("title") or play["who"])
        if "spotify" in (play.get("app") or "").lower():
            try:
                os.startfile(media.spotify_search(query))
                return
            except OSError:
                pass
        webbrowser.open(media.youtube_search(query))

    def focus_music(self, now: float):
        """What you most often had on during past focus sessions, if nothing plays now."""
        if not self.may("learn_media") or self.playlog.playing or self.store.muted("media:focus", now):
            return None
        spans = [(ts - (data or {}).get("minutes", 25) * 60, ts) for ts, data in self.store.events("focus_done", int(now - 30 * 86400))]
        if len(spans) < 2:
            return None
        return brain.favourite(brain.during(self.store.plays(int(now - 30 * 86400)), spans), now)

    def place_music(self, now: float, plays=None, usage=None):
        """What you usually have on in the place you are in, once you have settled there."""
        place = self.tracker.place
        if place is None or not self.may("learn_media") or self.playlog.playing:
            return None
        if now - self.tracker.place_since < 120 or self.tracker.category(place) in ("media", "system"):
            return None
        plays = self.store.plays(int(now - 30 * 86400)) if plays is None else plays
        usage = self.history(now)[0] if usage is None else usage
        return brain.place_music(plays, usage, place.id, now)

    def nudge_media(self, now: float) -> bool:
        if not self.may("learn_media") or self.playlog.playing or now - self.playlog.ended_at < 600:
            return False
        plays = self.store.plays(int(now - 30 * 86400))
        if len(plays) < 5:
            return False
        hour = dt.datetime.fromtimestamp(now).hour
        usage, days = self.history(now)
        if not self.store.muted("media:usual", now) and f"media:{hour}" not in self.said:
            seen = brain.listening_days(plays, days, hour) if len(days) >= 3 else 0
            pick = brain.favourite(plays, now, hour) if seen >= 3 and seen * 2 >= len(days) else None
            if pick and self.say_once(f"media:{hour}"):
                self.offer("media:usual", T("Around this time you often put on {who}. Play it?", who=pick["who"]), (self.play_label(pick), lambda: self.play(pick)), T("Not now"))
                return True
        place = self.tracker.place
        if place is not None and not self.store.muted("media:place", now) and f"media:in:{place.id}" not in self.said:
            pick = self.place_music(now, plays, usage)
            if pick and self.say_once(f"media:in:{place.id}"):
                self.offer("media:place", T("In {place} you usually have {who} on. Play it?", place=place.name, who=pick["who"]), (self.play_label(pick), lambda: self.play(pick)), T("Not now"))
                return True
        pick = brain.on_repeat(plays, now)
        if pick and not self.store.muted("media:similar", now) and not self.store.muted("media:repeat:" + pick["who"], now):
            self.store.mute("media:repeat:" + pick["who"], int(now + WEEK))
            self.offer(
                "media:similar",
                T("You played {who} {n} times this week. Want something similar?", who=pick["who"], n=pick["plays"]),
                (T("Find similar"), lambda: self.find_similar(pick["who"])),
                T("No thanks"),
            )
            return True
        return False

    def find_similar(self, artist: str) -> None:
        """Ideas like an artist: from the offline AI if it is set up, else a search you open yourself."""
        if self.ai.state == "ready":
            self.open_panel("chat")
            self.panel.send_chat(T("Suggest three artists similar to {who}.", who=artist))
        else:
            webbrowser.open(media.youtube_search(T("artists similar to {who}", who=artist)))

    # ------------------------------------------------------------------ "what should I do now?"

    def now_facts(self, now: float) -> advisor.Facts:
        place = self.tracker.place
        day = self.today_summary(now)
        rhythm = self.rhythm(now)
        known = self.store.places()
        following = None
        if place is not None and self.may("learn_routine"):
            target = brain.next_place(self.store.moves_from(place.id))
            if target and target in known:
                following = (target, known[target]["name"])
        return advisor.Facts(
            now=now,
            tasks=tuple(self.store.tasks()),
            goals=tuple(goal for goal in self.goals_today() if not goal["done"]),
            place_id=place.id if place else "",
            place_name=place.name if place else "",
            category=self.tracker.category(place),
            streak_s=self.tracker.streak,
            break_after_s=self.break_after_s(now),
            focusing=self.focus.focusing,
            on_break=self.focus.on_break,
            focus_count=day["focus_count"],
            focus_min=self.settings["focus_min"],
            active_s=day["active"],
            routines=tuple((routine.place, row["name"], routine.slot) for routine, row in self.due_routines(now)),
            next_place=following,
            usual_end=None if rhythm is None else rhythm[1] / 4,
            energy=self.condition.energy,
            music=self.place_music(now),
        )

    def what_now(self) -> None:
        """The menu's "What should I do now?": the cat's best ideas, each with its button."""
        found = advisor.ideas(self.now_facts(time.time()))
        text = found[0].text if len(found) == 1 else "\n".join(f"{i}. {idea.text}" for i, idea in enumerate(found, 1))
        buttons = [(idea.button, lambda i=idea: self.do_idea(i.action)) for idea in found if idea.action]
        self.voice.say(text, buttons, kind="reply", ttl=30)

    def do_idea(self, action: tuple) -> None:
        if action[0] == "tasks":
            self.open_panel("tasks")
        elif action[0] == "break":
            self.start_break()
        elif action[0] == "focus":
            self.start_focus()
        elif action[0] == "open":
            row = self.store.places().get(action[1])
            if row:
                self.open_place(row)
        elif action[0] == "play":
            self.play(action[1])

    # ------------------------------------------------------------------ the offline AI

    def ai_system(self, now: float, local=None) -> tuple:
        """Everything the model is told before your message: who the cat is and what it
        knows, in the two parts assistant.system_prompt gives. Always in English,
        whatever language the app is shown in: these are notes for the model, and it
        answers in the language you write in. `local`: for the model on this computer
        (True) or an online one (False); by default, for whichever answers now."""
        facts, feeling, _tasks, _notes = self.ai_facts(now)
        if local is None:
            local = getattr(self.ai.brain, "local", True)
        return self.ai_words(facts, feeling, local)

    def ai_words(self, facts: str, feeling, local: bool, asks=None) -> tuple:
        """`asks`: whether whatever the model wants done will wait for a click (by
        default: as the person set it, and as the running script has it)."""
        s = self.settings
        with plain():
            return assistant.system_prompt(
                s["name"], mood.MOOD_WORDS[feeling.mood], feeling.why, s["focus_min"], facts,
                pivot=local,  # the model on this computer is helped with Uzbek's alphabets
                style=s["ai_style"], length=s["ai_length"], off=[key for key, switch in ABILITY_SWITCHES if not s[switch]],
                ask_first=self.asks_first() if asks is None else asks,
            )

    def ai_facts(self, now: float) -> tuple:
        """(the facts as text, the cat's mood, the tasks shown {number: text}, the notes
        shown {number: text}). The numbers are how the model points at a task or a note."""
        with plain():
            feeling = mood.condition(self.day_facts(now))
            known, shown_tasks, shown_notes = self._ai_facts(now, feeling)
        return assistant.facts_text(known), feeling, shown_tasks, shown_notes

    def _ai_facts(self, now: float, feeling) -> tuple:
        clock = dt.datetime.fromtimestamp(now)
        s = self.settings
        day = self.today_summary(now)
        known = []
        named = self.ai_named = []  # the names in these facts: see ai_names()
        known.append(clock.strftime("Now: %A %d %B %Y, %H:%M."))
        place = self.tracker.place
        if place is not None and self.tracker.category(place) != "system":
            known.append(f"The user is in {place.name} ({apps.CATEGORY_NAMES.get(self.tracker.category(place), 'other').lower()}).")
            named.append(place.name)
        if self.may("learn_routine") and day["active"] >= 60:
            top = ", ".join(f"{name} ({duration(seconds)})" for name, seconds, _ in day["places"][:4])
            known.append(f"Today at the computer: {duration(day['active'])}. Most time in: {top}.")
            named += [name for name, _, _ in day["places"][:4]]
        known.append(f"Focus rounds today: {day['focus_count']}. Breaks: {day['breaks']}. Tasks finished today: {day['done']}. The user has now worked {int(self.tracker.streak // 60)} minutes without a break.")
        if self.focus.focusing:
            known.append(f"A focus timer is running: {self.focus.minutes_left(now)} min left.")
        about = " ".join(s["ai_about"].split())[:600]
        if about:
            known.append(f"About the user, in their own words: {about}")
        notes = self.store.notes()
        shown_notes = {note["id"]: note["text"] for note in notes}
        if notes:
            known.append("Notes you keep about the user (number: note; some are in the user's own words): " + "; ".join(f"{note['id']}: {note['text']}" for note in notes) + ".")
        # Every open task goes along, each with its number: that is how the model says
        # which one it means when it is asked to finish, move or delete one.
        waiting = self.store.tasks()
        known_places = self.store.places()
        shown_tasks = {}
        listed = []
        for task in waiting[:TASKS_TOLD]:
            shown_tasks[task["id"]] = task["text"]
            marks = []
            if task["place"]:
                marks.append("a note for when the user is in " + ((known_places.get(task["place"]) or {}).get("name") or task["place"]))
            elif task["due"]:
                marks.append(("overdue, was due " if task["due"] < now else "due ") + tasks.due_label(task["due"], clock))
            if task["goal"] == self.today:
                marks.append("a goal for today")
            listed.append(f"{task['id']}: {task['text']}" + (f" ({', '.join(marks)})" if marks else ""))
        if listed:
            more = f" And {len(waiting) - TASKS_TOLD} more that are not shown here." if len(waiting) > TASKS_TOLD else ""
            known.append("Open tasks (number: task): " + "; ".join(listed) + "." + more)
            # a task written in Uzbek is words, not a name: it follows the talk's alphabet
            named += [text for text in shown_tasks.values() if assistant.writing(text) != "uz-latn"]
        else:
            known.append("No open tasks.")
        finished = [task["text"] for task in self.store.finished(midnight(self.today))][-8:]
        if finished:
            known.append("Finished today: " + "; ".join(finished) + ".")
        goals = self.goals_today()
        if goals:
            known.append(f"Goals for today: {len(goals)}, of which {sum(1 for goal in goals if goal['done'])} finished.")
        this_week, last_week = self.week(0), self.week(1)
        hours = self.may("learn_routine")
        for label, week in (("This week so far", this_week), ("Last week", last_week)):
            if week["active"] >= 600 or week["done"] or week["focus_count"]:
                time_part = f"{duration(week['active'])} at the computer, " if hours else ""
                known.append(f"{label}: {time_part}{week['focus_count']} focus rounds, {week['done']} tasks finished.")
        if s["ai_may_open"]:
            can_open = apps.openable(known_places)
            if can_open:
                known.append("Can be opened: " + ", ".join(can_open) + ", and other programs installed on this computer.")
                named += can_open
        if self.may("learn_routine"):
            names = self.store.places()
            found = [f"{names[r.place]['name']} around {slot_label(r.slot)}" for r in self.routines(now)[:5] if r.place in names]
            if found:
                known.append("Routines the user has on days like today: opens " + ", ".join(found) + ".")
                named += [names[r.place]["name"] for r in self.routines(now)[:5] if r.place in names]
            rhythm = self.rhythm(now)
            if rhythm:
                known.append(f"Usually starts around {slot_label(rhythm[0])} and wraps up around {slot_label(rhythm[1])}.")
        if self.may("learn_media"):
            plays = self.store.plays(int(now - 30 * 86400))
            weight: dict = {}
            for play in plays:
                name = brain.who(play)
                if name:
                    weight[name] = weight.get(name, 0) + play["ended"] - play["started"]
            favourites = sorted(weight, key=lambda n: -weight[n])[:6]
            if favourites:
                known.append("Often listens to or watches: " + ", ".join(favourites) + ".")
                named += favourites
            if self.playlog.current:
                _app, title, artist = self.playlog.current["key"]
                known.append(f"Playing right now: {' - '.join(x for x in (artist, title) if x)}.")
                named += [artist or "", title or ""]
        today = clock.date()
        for name in days.names(today)[:1]:
            known.append(f"Today is {name}.")
        ahead = days.coming(self.store.own_days(), today)
        if ahead:
            known.append("Dates the user asked to be reminded of: " + "; ".join(f"{name} ({'today' if n == 0 else 'tomorrow' if n == 1 else f'in {n} days'})" for name, n in ahead[:6]) + ".")
        forecast = self.weather.fresh(now)
        if forecast is not None:
            line = f"The weather in {forecast['city']} now: {forecast['temp']} °C, {weather.SKY.get(forecast['code'], 'cloudy')}; today between {forecast['low']} and {forecast['high']} °C."
            soon = weather.coming(forecast, clock)
            if soon:
                line += f" {soon[0].capitalize()} is likely around {soon[1]}."
            known.append(line)
        thoughts = [idea.text for idea in advisor.ideas(self.now_facts(now)) if idea.key != "none"]
        if thoughts:
            known.append("Your own ideas for what the user could do now: " + " ".join(thoughts))
        from .extras import goal_facts

        known += goal_facts(self.store, dt.date.fromisoformat(self.today))
        known.append(f"Your energy is {feeling.energy} out of 100. You and the user are {mood.bond_name(self.bond).lower()}.")
        return known, shown_tasks, shown_notes

    def ask_ai(self, text: str, source: str = "window", look: int = 0) -> bool:
        """Put a question to the AI. `source` is where it was typed: the Chat "window", or
        the ask "box" by the cat, whose answer then comes in the cat's bubble. `look`: a
        window whose text is to go along with the question (see `readable_now`)."""
        if look:
            return self._ask_about(look, text, source)
        if self.ai.busy or self.ai.state != "ready":
            if source == "box":
                self.voice.say(T("One moment, I am still answering."), kind="reply", ttl=4)
            return False
        self.wished = self.goal_wish(text)  # "the report goal is at 70 %": set before the AI answers, so it knows
        facts, feeling, shown_tasks, shown_notes = self.ai_facts(time.time())
        self.ask_source = source
        return self.ai.ask(text, lambda local: self.ai_words(facts, feeling, local), keep=self.ai_names(), tasks=shown_tasks, notes=shown_notes)

    def _ask_about(self, hwnd: int, text: str, source: str) -> bool:
        """A question about what another program shows. Asked again here whether that
        program may be read, whoever is asking: the switch and the ticks decide, not the
        window that happens to be in front. And what is read stays on this computer
        unless the person said it may go to the online AI as well."""
        program, name = reader.identity(hwnd)
        online_ok = bool(self.settings["ai_read_online"])
        problem = ""
        if not self.may_read(program):
            problem = T("I may not read {name}: that is switched off in my AI brain tab.", name=name or "?")
        elif self.ai.busy:
            problem = T("One moment, I am still answering.")
        elif self.ai.local is None if not online_ok else self.ai.state != "ready":
            problem = T("What I read in other programs may only go to my AI on this computer, and that one is not ready.") if not online_ok else T("My AI brain is not ready.")
        if problem:
            self.voice.say(problem, [(T("AI brain"), lambda: self.open_panel("brain"))], kind="reply", ttl=14)
            return False
        facts, feeling, shown_tasks, shown_notes = self.ai_facts(time.time())
        self.ask_source = source
        # whatever the answer wants done will only be offered: the model is told so
        words = lambda local: self.ai_words(facts, feeling, local, asks=True)  # noqa: E731
        return self.ai.look_and_ask(hwnd, text, words, keep=self.ai_names(), tasks=shown_tasks, notes=shown_notes, online_ok=online_ok)

    def goal_wish(self, text: str) -> list:
        """A message that says how far one of the goals is ("my report goal is at 70 %")
        sets it. Read from the person's own words, so it works with any model. Returns the
        notes to show with the answer: what was done (with Undo), or the question about it."""
        from .extras import progress_wish

        if not self.settings["ai_may_edit"]:
            return []
        wish = progress_wish(self.store, text, dt.date.fromisoformat(self.today))
        if wish is None:
            return []
        goal, percent = wish
        before = goal["progress"]
        if percent == before:
            return []

        def again() -> None:
            window = getattr(self, "goals_window", None)
            if window is not None and window.win.winfo_exists():
                window.build()

        def carry_out():
            self.store.set_long_goal(goal["id"], percent)
            again()
            return dict(text=T('Goal "{goal}": {n} %', goal=goal["text"], n=percent), undo=lambda: (self.store.set_long_goal(goal["id"], before), again()))

        if self.asks_first():
            return [dict(mark="?", text=T('Set the goal "{goal}" to {n} %?', goal=goal["text"], n=percent), do=carry_out)]
        return [carry_out()]

    def ai_names(self) -> set:
        """Names that are written in Latin letters whatever alphabet the talk is in: the
        cat's, programs and sites, and what the model was just told about (the music you
        play, tasks written in English). When an Uzbek answer is put into Cyrillic
        letters, these are left as they are."""
        named = [self.settings["name"], *apps.KNOWN_NAMES.values(), *(site.name for site in apps.SITES), *self.ai_named]
        return translit.latin_words(" ".join(named))

    def run_ai_actions(self, actions: list, turn=None) -> list:
        """Carry out what the model proposed. Returns notes for the chat window, dicts
        with 'text' and, as the case may be:

            'undo'     a function that takes the thing back
            'do'       a function that carries it out: it has not been done yet, because
                       the person wants to be asked first. It returns the note to show then.
            'links'    (label, address) pairs to open in the browser
            'buttons'  (label, function) pairs
            'mark'     the sign before the text when it is not the usual tick

        What the person has switched off in the AI brain tab is dropped here, whatever
        the model says. `turn` is the assistant.Turn that was answered."""
        s = self.settings
        barred = {do for key, switch in ABILITY_SWITCHES if not s[switch] for do in assistant.ACTIONS_OF[key]}
        said = turn.text if turn is not None else ""
        known_notes = getattr(turn, "notes", {}) or {}
        clock = dt.datetime.now()
        notes = list(getattr(self, "wished", None) or [])  # what the message itself set (see goal_wish)
        self.wished = []
        for action in actions:
            do = action["do"]
            if do in barred:
                continue
            if do == "offer":
                # The app's own reading of the message ("I bought the milk" says that "Buy milk"
                # is done, "delete the milk task" that it is to go) where the model let it pass:
                # asked about with a button, never done unasked.
                what = "remove" if action.get("what") == "remove" else "done"
                step = None if what in barred else self._ai_step({"do": what, "task": action["task"]}, clock, said, known_notes)
                if isinstance(step, tuple):
                    notes.append(dict(mark="?", text=step[0], do=step[1]))
                continue
            if do == "suggest":
                notes.append(dict(text=T("Look these up:"), links=[(item, media.youtube_search(item)) for item in action["items"]]))
                continue
            if do == "unsure":
                notes.append(dict(mark="!", text=T("I was not sure which task you meant, so I changed nothing."), buttons=[(T("Open tasks"), lambda: self.open_panel("tasks"))]))
                continue
            if do == "nothing":
                if "move" not in barred:
                    notes.append(dict(mark="!", text=T("I did not manage to do that by myself, so I changed nothing."), buttons=[(T("Open tasks"), lambda: self.open_panel("tasks"))]))
                continue
            step = self._ai_step(action, clock, said, known_notes)
            if step is None:
                continue
            if isinstance(step, dict):  # nothing to carry out, only something to say
                notes.append(step)
                continue
            question, carry_out = step
            # An answer that had another program's text before it never acts by itself,
            # whatever is switched on: other people wrote that text.
            if self.asks_first() or getattr(turn, "material", None):
                notes.append(dict(mark="?", text=question, do=carry_out))
            else:
                done = carry_out()
                if done:
                    notes.append(done)
        self.refresh_panel()
        return notes

    def _ai_step(self, action: dict, clock, said: str, known_notes: dict):
        """One thing the model wants done, made ready: (the question to ask about it, a
        function that does it and returns the note to show), or a note alone when there
        is nothing to do, or None when there is nothing to say either."""
        do = action["do"]
        again = self.refresh_panel
        if do == "remind":
            text = action["text"]
            when = tasks.parse_when(action.get("when", ""), clock)
            due = int(when.timestamp()) if when else None
            label = tasks.due_label(due, clock)

            def remind():
                task_id = self.store.add_task(text, due=due)
                shown = T("Reminder set: {text} ({when})", text=text, when=label) if label else T("Added to your list: {text}", text=text)
                return dict(text=shown, undo=lambda: (self.store.delete_task(task_id), again()))

            return (T("Remind you: {text} ({when})?", text=text, when=label) if label else T("Add to your list: {text}?", text=text)), remind
        if do in ("done", "move", "remove"):
            task = self.store.task(action["task"])
            if not task or task["done"]:
                return None
            task_id, text = task["id"], task["text"]
            if do == "done":
                def finish():
                    self.complete_task(task_id)
                    return dict(text=T("Finished: {text}", text=text), undo=lambda: (self.store.update_task(task_id, done=None), again()))

                return T("Tick off: {text}?", text=text), finish
            if do == "remove":
                def remove():
                    self.store.delete_task(task_id)
                    return dict(text=T("Deleted: {text}", text=text), undo=lambda: (self.store.restore_task(task), again()))

                return T("Delete: {text}?", text=text), remove
            when = tasks.parse_when(action.get("when", ""), clock)
            if when is None or task["place"]:
                return dict(mark="!", text=T("I did not understand the new time for: {text}", text=text), buttons=[(T("Open tasks"), lambda: self.open_panel("tasks"))])
            due = int(when.timestamp())
            label = tasks.due_label(due, clock)

            def move():
                self.store.update_task(task_id, due=due, shown=None, tries=0)
                back = lambda: (self.store.update_task(task_id, due=task["due"], shown=task["shown"], tries=task["tries"]), again())
                return dict(text=T("Moved: {text} ({when})", text=text, when=label), undo=back)

            return T("Move: {text} ({when})?", text=text, when=label), move
        if do == "goals":
            items = action["items"]
            listed = "; ".join(items)

            def goals():
                return dict(text=T("Goals for today: {goals}", goals=listed), undo=self.make_goals(items, reuse=True))

            return T("Make these today's goals: {goals}?", goals=listed), goals
        if do == "focus":
            minutes = int(action.get("minutes") or self.settings["focus_min"])

            def focus():
                self.start_focus(minutes)
                return dict(text=T("Focus timer started: {n} min", n=self.focus_len), undo=self.stop_focus)

            return T("Start a focus timer: {n} min?", n=minutes), focus
        if do == "break":
            def rest():
                self.start_break()
                return dict(text=T("Break started: {n} min", n=self.settings["break_min"]), undo=self.end_break)

            return T("Start a break: {n} min?", n=self.settings["break_min"]), rest
        if do == "open":
            name = action["name"]
            address = apps.typed_address(name, said)
            target = None if address else apps.find_target(name, self.store.places())
            if not address and target is None:
                return dict(mark="!", text=T("I could not find {name} on this computer.", name=name), links=[(T("Search the web"), search_url(name))])
            shown = address or target.name

            def open_it():
                if not (self.open_address(address) if address else self.open_target(target)):
                    return dict(mark="!", text=T("I couldn't open {name} from here.", name=shown))
                return dict(text=T("Opened: {name}", name=shown))

            return T("Open {name}?", name=shown), open_it
        if do == "search":
            query = action["query"]

            def search():
                self.open_address(search_url(query))
                return dict(text=T("Searched the web for: {query}", query=query))

            return T("Search the web for: {query}?", query=query), search
        if do == "remember":
            text = action["text"]

            def remember():
                note_id = self.store.add_note(text)
                if not note_id:  # known already
                    return None
                return dict(text=T("I will remember: {text}", text=text), undo=lambda: (self.store.delete_note(note_id), again()))

            return T("Remember: {text}?", text=text), remember
        if do == "forget":
            note = next((row for row in self.store.notes() if row["id"] == action["note"]), None)
            if note is None:
                return None

            def forget():
                self.store.delete_note(note["id"])
                return dict(text=T("Forgotten: {text}", text=note["text"]), undo=lambda: (self.store.restore_note(note), again()))

            return T("Forget: {text}?", text=note["text"]), forget
        return None

    def open_address(self, address: str) -> bool:
        """Open a web address in the person's own browser."""
        try:
            return bool(webbrowser.open(address))
        except (OSError, webbrowser.Error):
            return False

    def open_target(self, target) -> bool:
        """Open what apps.find_target found for a name. True if it was started."""
        try:
            if target.kind == "site":
                return self.open_address(target.what)
            if target.kind == "place":
                row = self.store.places().get(target.what)
                if row is None:
                    return False
                hwnd = win32.window_of_exe(row.get("path") or "") if row.get("path") else 0
                if hwnd and win32.bring_to_front(hwnd):
                    return True
                if row.get("path") and os.path.exists(row["path"]):
                    os.startfile(row["path"])
                    return True
                site = apps.SITE_BY_KEY.get(target.what)
                return bool(site and site.url and self.open_address(site.url))
            os.startfile(target.what)  # a Start-menu shortcut, or one of Windows' own tools from the fixed table
            return True
        except OSError:
            log.info("could not open %s", target.name)
            return False

    def clear_conversation(self) -> None:
        """Forget what was said in Chat, here and in what is kept for the next start."""
        self.ai.clear_talk()
        self.chat_log = []
        if self.panel is not None:
            self.panel.clear_chat()

    def on_ai_ready(self) -> None:
        if self.ai.both:
            text = T("My AI brain on this computer is ready too. It answers when the online one cannot be reached.")
        elif self.ai.online:
            text = T("My AI brain on this computer is ready. For now the online one answers: you can change that in the AI brain tab.")
        else:
            text = T('My AI brain is ready. Pick "Ask me" in my menu and we can talk.')
        self.voice.say(text, kind="nudge", emote="cheer", ttl=14)
        self.refresh_panel()

    def on_ai_failed(self, error: str) -> None:
        self.voice.say(T("I could not finish setting up my AI brain. {error}", error=error), [(T("Try again"), self.ai.setup), (T("Later"), _noop)], kind="nudge")
        self.refresh_panel()

    # ------------------------------------------------------------------ small talk and petting

    def small_talk(self, now: float) -> None:
        way = self.settings["chatter"]
        if way == "off" or now < self.next_chat:
            return
        lo, hi = (25, 45) if way == "normal" else (70, 120)
        self.next_chat = now + random.uniform(lo, hi) * 60
        self.voice.say(self.condition.why if random.random() < 0.4 else lines.chat(self.scene.category), kind="chat")

    def on_pet_clicked(self) -> None:
        now = time.time()
        if self.pet.tucked:  # a click on the face at the edge brings the cat back
            self.untuck()
            return
        if self.focus.focusing:
            self.voice.say(T("Shh, focusing. {n} min left.", n=self.focus.minutes_left(now)), kind="reply", ttl=4)
            return
        if self.focus.on_break:
            self.voice.say(T("Break: {n} min left.", n=self.focus.minutes_left(now)), kind="reply", ttl=4)
            return
        self.store.log("pet", ts=now)
        self.pets_today += 1
        feeling = self.condition
        hello = self.last_pet is None or now - self.last_pet > 600  # the first stroke in a while gets a small trill before the purr
        self.last_pet = now
        if self.pets_today <= 5:
            self.add_bond(1)
        self.pet.emote("happy", 1.6)
        self.sound("greet" if hello else "purr")
        if random.random() < 0.3 and not self.voice.busy():
            said = feeling.why if feeling.mood in ("lonely", "worried", "tired", "sleepy", "proud") else lines.purr()
            self.voice.say(said, kind="reply", ttl=5, emote="happy")

    def on_pet_grabbed(self) -> None:
        self.voice.hush()
        self.menu.close()

    # ------------------------------------------------------------------ menu and windows

    def show_menu(self, x: int, y: int) -> None:
        now = time.time()
        s = self.settings
        feeling = T(mood.MOOD_WORDS[self.condition.mood]).lower()
        keys = hotkeys.merged(s["hotkeys"])

        def with_key(text: str, name: str) -> str:
            return text + ("\t" + keys[name] if keys.get(name) and name not in self.tray.taken else "")

        items: list = [(f"{s['name']}  ·  {feeling}", None)]
        items.append((T("What should I do now?"), self.what_now))
        items.append((with_key(T("Ask me..."), "ask"), self.quick_ask))
        items.append(None)
        if self.focus.focusing:
            items.append((T("Stop focus") + "\t" + T("{n} min left", n=self.focus.minutes_left(now)), self.stop_focus))
        else:
            items.append((T("Start focus") + "\t" + T("{n} min", n=s["focus_min"]), self.start_focus))
        if self.focus.on_break:
            items.append((T("End break") + "\t" + T("{n} min left", n=self.focus.minutes_left(now)), self.end_break))
        else:
            items.append((T("Take a break") + "\t" + T("{n} min", n=s["break_min"]), self.start_break))
        items.append(None)
        items.append((with_key(T("Add a task..."), "task"), self.quick_task))
        place = self.tracker.place
        if place and self.tracker.category(place) != "system":
            items.append((T("Remind me in {place}...", place=place.name), lambda p=place: self.ask_note(p)))
        items.append((T("Goals for today..."), self.ask_goals))
        items.append((T("Habits and goals"), self.open_goals))
        items.append(None)
        items.append((T("Play with me"), self.play_with_cat))
        items.append(None)
        items.append((T("Open the window"), lambda: self.open_panel("today")))
        items.append(None)
        if self.pet.hidden:
            items.append((with_key(T("Show the cat"), "toggle"), self.toggle_hidden))
        elif self.pet.tucked:
            items.append((with_key(T("Come out"), "toggle"), self.untuck))
        else:
            items.append((T("Hide for an hour"), lambda: self.hide_for(60)))
            items.append((with_key(T("Hide"), "toggle"), self.toggle_hidden))
        items.append((T("Quit"), self.quit))
        self.menu.popup(x, y, items)

    # ------------------------------------------------------------------ the ask box and what comes back from it

    def quick_ask(self) -> None:
        """Open the box by the cat (or close it, if it is open). With the AI it is for
        questions; without, what you type becomes a task."""
        if self.quick.open:
            self.quick.close()
            return
        self.voice.hush()
        self.menu.close()
        if self.ai.state == "ready":
            self.ai.warm()  # so the model is in memory by the time the question is typed
            seen = self.readable_now()  # the program in front, if the person lets the cat read it
            hwnd = seen[0] if seen else 0
            self.quick.show(
                T("Ask me anything, or tell me what to do: remind, finish a task, open a program. Esc closes."),
                lambda text: self.ask_ai(text, "box", look=hwnd if self.quick.ticked else 0),
                tick=T("With what {name} shows", name=seen[2]) if seen else "",
            )
        elif self.ai.state == "setup":  # it is on its way: say how far, so nobody has to wonder
            self.quick.show(T("My AI brain is still being set up. I will tell you when we can talk.") + " " + self.ai.progress_words(), self.note_or_question)
        else:
            self.quick.show(T("I cannot answer questions yet: my AI brain is not set up. What you type here becomes a task."), self.note_or_question)

    def note_or_question(self, text: str) -> None:
        """Typed into the ask box while there is no AI to ask. A task is taken as one. A
        question is not quietly filed as a task: the cat says what it would need to answer."""
        if not text.rstrip().endswith(("?", "？")):
            self.add_task_from_text(text)
            return
        keep = (T("Keep it as a task"), lambda: self.add_task_from_text(text))
        if self.ai.state == "setup":
            self.voice.say(T("My AI brain is still being set up. I will tell you when we can talk.") + " " + self.ai.progress_words(), [keep], kind="reply", ttl=16)
        elif self.ai.state == "nokey":
            self.voice.say(T("To answer I need the key of the online AI you chose."), [(T("AI brain"), lambda: self.open_panel("brain")), keep], kind="reply", ttl=20)
        else:
            self.voice.say(T("To answer questions I need my AI brain, and it is not set up yet."), [(T("Set up now"), lambda: self.open_panel("chat")), keep], kind="reply", ttl=20)

    def quick_task(self) -> None:
        self.voice.hush()
        self.menu.close()
        self.quick.show(T('Add a time at the end and I will remind you: "at 15:30", "in 20 min", "tomorrow 9:00".'), self.add_task_from_text)

    def on_ai(self, what: str, payload) -> None:
        """What the AI is doing, as it happens: kept for the Chat window, and shown in the
        cat's bubble when the question came from the ask box."""
        box = self.ask_source == "box"
        script = self.script_now if self.ask_source == "script" else None
        if what == "reading":  # a window is being read for this question: said, so it never happens unseen
            if box or script is not None:
                self.voice.say(T("Reading {name}...", name=payload), kind="reply", ttl=30)
                self.reading_said = True
        elif what in ("answer", "error") and script is not None and self.reading_said:
            self.voice.hush()  # "Reading ..." makes way: a script's answer comes like a reminder, and would wait behind it
        if what in ("answer", "error"):
            self.reading_said = False
        if what == "reading":
            pass
        elif what == "asked":
            self.chat_log.append(("you" if script is None else "script:" + script["name"], payload, ()))
            if box:
                self.voice.say(T("Thinking..."), kind="reply", ttl=60)
        elif what == "answer":
            reply, notes = payload
            self.chat_log.append(("cat", reply, tuple(notes)))
            if box:
                self.show_answer(reply, notes)
            elif script is not None:  # nobody asked just now: it comes like a reminder, under the script's name
                self.show_answer(reply, notes, title=script["name"], kind="alert")
                self.script_now = None
        elif what == "error":
            self.chat_log.append(("error", payload, ()))
            if box:
                self.voice.say(T("I could not answer: {error}", error=payload), kind="reply", ttl=12)
            elif script is not None:
                self.voice.say(T('I could not run "{name}": {error}', name=script["name"], error=payload), kind="alert", ttl=16)
                self.script_now = None
        del self.chat_log[:-80]

    def show_answer(self, reply: str, notes: list, title: str = "", kind: str = "reply") -> None:
        """An answer in the cat's bubble: its words, what it did, and what can be done
        next. A long answer is cut short there; the whole of it is in the Chat window.
        `title`: the name of the daily script whose answer this is."""
        said, cut = clipped(reply or T("..."), *BUBBLE_ROOM)
        text = [f"{title}: {said}" if title else said]
        undo = [note["undo"] for note in notes if note.get("undo")]
        waiting = [note["do"] for note in notes if note.get("do")]
        more: list = []
        for note in notes:
            text.append(note.get("mark", "✓") + " " + note["text"])
            more += [(label, lambda u=url: webbrowser.open(u)) for label, url in note.get("links", ())]
            more += list(note.get("buttons", ()))
        buttons = []
        if waiting:
            def do_all() -> None:  # the person said yes: carry out what was asked about, and show it
                self.show_answer(T("Done."), [done for done in (do() for do in waiting) if done])

            buttons += [(T("Do it"), do_all), (T("No"), _noop)]
        if cut:
            buttons.append((T("Read it all"), lambda: self.open_panel("chat")))
        buttons.append((T("Reply"), self.quick_ask))
        if undo:
            buttons.append((T("Undo"), lambda: [fn() for fn in undo]))
        buttons += [(label if len(label) <= 26 else label[:25] + "…", fn) for label, fn in more[:3]]
        whole = "\n".join(text)
        self.voice.say(whole, buttons, kind=kind, ttl=16 + len(whole) * 0.06)

    def _panel(self):
        if self.panel is None:
            from .panel import Panel  # the big window is built only when first opened

            self.panel = Panel(self)
        return self.panel

    def open_panel(self, tab: str = "today") -> None:
        self._panel().show(tab)

    def refresh_panel(self) -> None:
        if self.panel is not None:
            self.panel.refresh()

    def ask_note(self, place) -> None:
        from .panel import ask

        def save(text: str, every_time: bool) -> None:
            self.store.add_task(text, place=place.id, repeat=every_time)
            self.voice.say(T("Okay. Next time you are in {place}, I'll remind you.", place=place.name), kind="reply", ttl=6)
            self.refresh_panel()

        ask(self, T("In {place}", place=place.name), T("What should I remind you of when you open {place}?", place=place.name), save, T("Every time, not just once"))

    def welcome(self) -> None:
        from .panel import Welcome

        Welcome(self)

    # ------------------------------------------------------------------ numbers for the panel

    def summary(self, day: str) -> dict:
        """One day in numbers."""
        known = self.store.places()
        rows = []
        categories: dict = {}
        for place, seconds in self.tracker.day_totals(day).items():
            row = known.get(place) or {}
            category = row.get("category") or "other"
            rows.append((row.get("name") or place, seconds, category))
            categories[category] = categories.get(category, 0) + seconds
        rows.sort(key=lambda r: -r[1])
        start = midnight(day)
        end = start + 86400
        sessions = self.store.events("focus_done", start, end)
        return dict(
            active=sum(seconds for _, seconds, _ in rows),
            places=rows,
            categories=categories,
            focus_count=len(sessions),
            focus_min=sum((data or {}).get("minutes", 0) for _, data in sessions),
            breaks=self.store.count("break", start, end) + self.store.count("break_start", start, end),
            done=self.store.done_today(start),
        )

    def today_summary(self, now: float) -> dict:
        """Today's numbers, at most twenty seconds old."""
        stamp, day, data = self.summary_cache
        if data is None or day != self.today or now - stamp > 20:
            data = self.summary(self.today)
            self.summary_cache = (now, self.today, data)
        return data

    def job_title(self) -> str:
        """What the cat calls itself, from the kind of work you did most this week."""
        first = (dt.date.fromisoformat(self.today) - dt.timedelta(days=6)).isoformat()
        known = self.store.places()
        per: dict = {}
        for places in self.tracker.usage(first, self.today).values():
            for place, slots in places.items():
                category = (known.get(place) or {}).get("category") or "other"
                per[category] = per.get(category, 0) + sum(slots.values())
        per.pop("other", None)
        per.pop("system", None)
        return lines.job_title(max(per, key=lambda c: per[c]) if per else "")

    # ------------------------------------------------------------------ settings and shutdown

    def apply_settings(self) -> None:
        """Called after the panel changed something."""
        self.store.save_settings()
        self.tracker.learn = self.may("learn_routine")
        self.pet.apply_capture()
        self.pet.apply_eye()
        self.voice.bubble.apply_capture()
        self.sync_watcher()
        self.stretch_cache = (0.0, None)
        self.ai.settle()
        if not self.settings["ai_keep_talk"]:
            self.store.clear_talk()  # nothing of the conversation outlasts the app then
        self.tray.set_shortcuts(hotkeys.merged(self.settings["hotkeys"]))
        if self.settings["sounds"]:
            self.sounds.prepare()  # so the first purr is there the moment the cat is petted
        if bool(self.settings["autostart"]) != autostart.enabled():
            if not autostart.set_enabled(bool(self.settings["autostart"])):
                self.settings["autostart"] = autostart.enabled()
        try:
            tray.write_icon(self.icon_path, self.settings["coat"])
        except OSError:
            pass

    def rename_cat(self, name: str) -> None:
        """Give the cat another name: from the field in Settings, or from a click on its
        name at the top of the window. It answers with the new one."""
        name = " ".join(str(name).split())[:20]
        if not name or name == self.settings["name"]:
            return
        self.settings["name"] = name
        self.apply_settings()
        self.refresh_panel()
        if self.panel is not None:
            self.panel.cat_name.set(name)
        self.voice.say(T("{name}! I like it. That is my name from now on.", name=name), kind="reply", ttl=7, emote="happy")

    def set_language(self, code: str) -> None:
        """Switch the app's own words to another language, at once."""
        if code == self.settings.get("language"):
            return
        self.settings["language"] = code
        self.store.save_settings()
        load_language(code)
        self.condition = mood.condition(self.day_facts(time.time()))
        tab = None
        if self.panel is not None:  # its texts were made in the old language: build it again
            tab = self.panel.current() if self.panel.visible else None
            self.panel.destroy()
            self.panel = None
        self.menu.close()
        if tab:
            self.open_panel(tab)
        self.voice.say(T("All right, this is how I talk from now on."), kind="reply", ttl=6, emote="happy")

    def forget_everything(self) -> None:
        self.tracker.forget()
        self.playlog.current = None
        self.store.forget_learning()
        self.clear_conversation()
        self.said = set()
        self.routine_cache = (0.0, [])
        self.rhythm_cache = (0.0, None)
        self.stretch_cache = (0.0, None)
        self.summary_cache = (0.0, "", None)
        self.voice.say(T("Done. I forgot everything I had learned."), kind="reply", ttl=6)
        self.refresh_panel()

    def quit(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            self.quick.close()
            if self.panel is not None:
                self.panel.destroy()  # with its clock, which would otherwise tick once more into a window that is gone
                self.panel = None
            self.tracker.flush()
            self.playlog.close()
            if self.watcher is not None:
                self.watcher.stop()
            self.ai.shutdown()
            self.tray.stop()
            self.pet.destroy()
            self.store.save_settings()
            self.store.close()
        except Exception:
            log.exception("quit")
        self.root.destroy()


def setup_logging(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / "workcat.log", maxBytes=200_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mycat", description="A desk cat that sits on the window you work in.")
    parser.add_argument("--data", help="folder for settings and what the cat learns (default: %%LOCALAPPDATA%%\\MyCat)")
    parser.add_argument("--check", metavar="REPORT", help="start once on an empty throwaway data folder, write what was loaded and from where into REPORT (a JSON file), and exit")
    parser.add_argument("--autostart", choices=("on", "off"), help="first switch 'Start with Windows' on or off (the setup program passes on what was ticked in it)")
    args = parser.parse_args(argv)
    if args.check:
        from .check import run

        return run(Path(args.check))
    if not args.data:
        # What an earlier version left under the app's earlier name is taken over: its data
        # folder gets the new name (in one step, or at a later start if it is in use now),
        # and so does its "start with Windows" entry.
        adopt_old_folder()
        autostart.adopt_old_value()
    folder = Path(args.data) if args.data else default_folder()
    setup_logging(folder)
    if args.autostart and not args.data:
        autostart.set_enabled(args.autostart == "on")
    name = instance_name(folder)
    if not win32.single_instance(name):
        log.info("already running: asking that cat to show itself")
        tray.call_running(name)
        return 0
    try:
        App(folder).run()
    except Exception:
        log.exception("fatal")
        return 1
    return 0
