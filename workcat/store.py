"""Everything the cat remembers, kept on this computer only.

settings.json  your choices, readable and editable by hand
workcat.db     what it learned: time per app, what played, tasks, what you answered

Nothing in this file talks to the network.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from . import APP_NAME, OLD_NAME

DEFAULTS = {
    "first_run_done": False,
    "language": "en",
    "name": "Mitti",
    "coat": "grey",
    "size": 0,  # 0 = pick from the screen's scaling; else 2, 3 or 4
    "outline": True,
    "follow_window": True,
    "chatter": "normal",  # off, rare, normal
    "focus_min": 25,
    "break_min": 5,
    "break_after_min": 50,  # remind to stretch after this much work without a pause; 0 = never
    "adaptive_breaks": True,  # remind earlier if you usually pause sooner than that
    "learn_routine": True,  # which apps you use and when
    "learn_sites": True,  # recognise well-known sites from the browser tab's title
    "learn_media": False,  # titles of what plays, for music and video suggestions
    "ai_model": "standard",  # the offline chat AI: "small", "standard" or "better"
    "ai_source": "offline",  # who answers: "offline" (this computer), "online" (a service, with your key), or "both" (online while it can be reached, this computer when not)
    "ai_service": "claude",  # which online service: see cloud.SERVICES
    "ai_address": "",  # the address of an online service that is not in the list
    "ai_online_model": "",  # the model to ask there; "" = the service's usual one
    "ai_key": "",  # the key for the online service, locked to your Windows account (never readable text)
    "ai_keep_ready": False,  # keep the offline model loaded for as long as the app runs: quicker, uses memory
    "ai_style": "playful",  # how the cat talks: "playful", "friendly" or "plain"
    "ai_length": "normal",  # how much it says: "short", "normal" or "detailed"
    "ai_about": "",  # what you wrote about yourself for the AI
    "ai_memory": True,  # it may note down lasting things you tell it about yourself
    "ai_keep_talk": True,  # the conversation is still known after a restart
    "ai_may_add": True,  # what the AI may do by itself: add reminders and tasks,
    "ai_may_edit": True,  # finish, move and delete tasks, set the day's goals,
    "ai_may_timer": True,  # start the focus timer and breaks,
    "ai_may_open": True,  # open programs and sites, and search the web
    "ai_ask_first": False,  # ask before changing or opening anything (otherwise: do it, and show Undo)
    "ai_may_read": False,  # read what another program's window shows, for a question or a daily script that asks for it
    "ai_read_programs": [],  # ... and only of these, which the person ticked: "telegram", "chrome"
    "ai_read_names": {},  # ... as people call them: {"telegram": "Telegram"}
    "ai_read_online": False,  # ... and whether that text may go to the online AI too (otherwise only to the one on this computer)
    "plan_morning": True,  # offer a plan for the day each morning (when an AI is there to make one)
    "hide_in_fullscreen": True,
    "quiet_in_calls": True,
    "hide_from_capture": True,  # keep the cat out of screenshots and screen sharing
    "autostart": False,
    "hotkeys": {},  # shortcut keys you changed, e.g. {"ask": "Ctrl+Alt+Space"}; see hotkeys.py for the usual ones
    "tucked": {},  # where the cat is tucked away at a screen edge, e.g. {"side": "right", "at": 0.4}; {} = not tucked
    "goals_ask": True,  # ask for your three goals each morning
    "recap": True,  # tell you about your day when you finish
    "week_note": True,  # point to the weekly report once a week
    "eye_rest_min": 0,  # remind you to rest your eyes every this many minutes; 0 = never
    "water_min": 0,  # remind you to drink water every this many minutes; 0 = never
    "nudge_goals": "sometimes",  # bring up an open task or a goal now and then, with a joke: off, sometimes, often
    "nudge_meals": True,  # ask about breakfast and lunch
    "breakfast_until": 10,  # ... about breakfast until this hour,
    "lunch_hour": 13,  # ... about lunch from this one
    "nudge_late": True,  # say that it is late,
    "late_hour": 23,  # ... from this hour on
    "nudge_days": True,  # say in the morning what kind of day it is (well-known days, and the person's own dates)
    "weather": True,  # tell the weather: this asks open-meteo.com, the one thing fetched without being asked each time
    "weather_city": "",  # the city for it; empty: the capital of the country Windows is set to
    "sounds": False,  # the cat's voice: a small meow with a reminder, a purr when petted
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, slot INTEGER NOT NULL, place TEXT NOT NULL,
    seconds INTEGER NOT NULL, PRIMARY KEY (day, slot, place));
CREATE TABLE IF NOT EXISTS places (place TEXT PRIMARY KEY, name TEXT, category TEXT, path TEXT,
    custom INTEGER NOT NULL DEFAULT 0, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS plays (id INTEGER PRIMARY KEY, started INTEGER NOT NULL, ended INTEGER NOT NULL,
    app TEXT, title TEXT, artist TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created INTEGER NOT NULL,
    due INTEGER, place TEXT, repeat INTEGER NOT NULL DEFAULT 0, done INTEGER, shown INTEGER,
    tries INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (ts INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT);
CREATE INDEX IF NOT EXISTS events_kind ON events (kind, ts);
CREATE TABLE IF NOT EXISTS mutes (key TEXT PRIMARY KEY, until INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS moves (src TEXT NOT NULL, dst TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (src, dst));
CREATE TABLE IF NOT EXISTS feedback (key TEXT PRIMARY KEY, yes INTEGER NOT NULL DEFAULT 0, no INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0, last INTEGER);
CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS talk (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, language TEXT, role TEXT NOT NULL,
    content TEXT NOT NULL, shown TEXT);
CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS habit_days (habit INTEGER NOT NULL, day TEXT NOT NULL, PRIMARY KEY (habit, day));
CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY, span TEXT NOT NULL, period TEXT NOT NULL, text TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS own_days (id INTEGER PRIMARY KEY, name TEXT NOT NULL, month INTEGER NOT NULL, day INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS scripts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, text TEXT NOT NULL, at INTEGER NOT NULL,
    days INTEGER NOT NULL DEFAULT 127, enabled INTEGER NOT NULL DEFAULT 1, acts INTEGER NOT NULL DEFAULT 0, look TEXT, last TEXT);
"""

FOREVER = 2**62
NOTES_KEPT = 40  # things the AI may keep in mind about you; the oldest make room
NOTE_LENGTH = 200
TALK_KEPT = 40  # lines of conversation that outlast a restart
SCRIPTS_MOST = 12  # daily scripts a person can have
EVERY_DAY = 0b1111111  # the days a script runs on: one bit a day, Monday first
WORKDAYS = 0b0011111


def _homes() -> tuple:
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
    return base / APP_NAME, base / OLD_NAME


def default_folder() -> Path:
    """Where the cat keeps what it remembers. Up to 0.6 the app, and with it this folder,
    had another name: where only the folder of that name is there, it is the one to use.
    (Looking never changes anything; `adopt_old_folder` is what renames it.)"""
    folder, old = _homes()
    return old if old.is_dir() and not folder.exists() else folder


def adopt_old_folder() -> bool:
    """Give the data folder of the app's earlier name its new one, in one step: settings,
    tasks, notes and the AI move along, nothing is copied. True if it was renamed.

    If something in it is in use just now (an older cat is still running, the AI engine
    is busy), it stays where it is, the cat goes on with it there, and this is tried
    again at the next start."""
    folder, old = _homes()
    if not old.is_dir() or folder.exists():
        return False
    try:
        old.rename(folder)
        return True
    except OSError:
        return False


class Store:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.folder / "settings.json"
        self.fresh = not self.settings_path.exists()  # nobody has chosen anything here yet
        self.settings = dict(DEFAULTS)
        self._load_settings()
        self.db = sqlite3.connect(str(self.folder / "workcat.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Added later: a database made by an older version gets the column now.
        if "goal" not in {row["name"] for row in self.db.execute("PRAGMA table_info(tasks)")}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN goal TEXT")  # the day ("2026-11-12") this task is one of the three goals of
        self.db.commit()
        # The cat's usual name was Miso and is Mitti now. A cat still carrying the old usual
        # name takes the new one, once; after that the name is whatever it is called.
        if not self.get("mitti"):
            if not self.fresh and self.settings["name"] == "Miso":
                self.settings["name"] = "Mitti"
                self.save_settings()
            self.put("mitti", True)

    # ------------------------------------------------------------------ settings

    def _load_settings(self) -> None:
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        for key, default in DEFAULTS.items():
            value = saved.get(key, default)
            if type(value) is type(default):  # a hand-edited wrong type falls back to the default
                self.settings[key] = value
        # Up to 0.6 "the one on this computer answers when the online AI cannot be reached"
        # was a switch beside the online AI. It is a choice of its own now: "both".
        if self.settings["ai_source"] == "online" and saved.get("ai_fallback") is True:
            self.settings["ai_source"] = "both"

    def save_settings(self) -> None:
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.settings_path)

    # ------------------------------------------------------------------ time per place

    def add_usage(self, rows: dict) -> None:
        """rows: (day, slot, place) -> seconds to add."""
        if not rows:
            return
        self.db.executemany(
            "INSERT INTO usage (day, slot, place, seconds) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (day, slot, place) DO UPDATE SET seconds = seconds + excluded.seconds",
            [(day, slot, place, int(seconds)) for (day, slot, place), seconds in rows.items()],
        )
        self.db.commit()

    def usage(self, first_day: str, last_day: str) -> dict:
        """day -> place -> slot -> seconds, for first_day..last_day inclusive."""
        out: dict = {}
        for row in self.db.execute("SELECT day, slot, place, seconds FROM usage WHERE day BETWEEN ? AND ?", (first_day, last_day)):
            out.setdefault(row["day"], {}).setdefault(row["place"], {})[row["slot"]] = row["seconds"]
        return out

    def see_place(self, place: str, name: str, category: str, path: str, now: int) -> None:
        self.db.execute(
            "INSERT INTO places (place, name, category, path, last_seen) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (place) DO UPDATE SET name = excluded.name, path = excluded.path, last_seen = excluded.last_seen, "
            "category = CASE WHEN places.custom THEN places.category ELSE excluded.category END",
            (place, name, category, path, now),
        )
        self.db.commit()

    def places(self) -> dict:
        return {row["place"]: dict(row) for row in self.db.execute("SELECT * FROM places")}

    def set_category(self, place: str, category: str) -> None:
        self.db.execute("UPDATE places SET category = ?, custom = 1 WHERE place = ?", (category, place))
        self.db.commit()

    # ------------------------------------------------------------------ what played

    def add_play(self, started: int, ended: int, app: str, title: str, artist: str, kind: str) -> None:
        self.db.execute("INSERT INTO plays (started, ended, app, title, artist, kind) VALUES (?, ?, ?, ?, ?, ?)", (started, ended, app, title, artist, kind))
        self.db.commit()

    def plays(self, since: int) -> list:
        return [dict(row) for row in self.db.execute("SELECT * FROM plays WHERE started >= ? ORDER BY started", (since,))]

    # ------------------------------------------------------------------ tasks and notes

    def add_task(self, text: str, due=None, place=None, repeat: bool = False, now=None, goal=None) -> int:
        """`goal` is the day this task is one of the day's three goals of, if it is."""
        cur = self.db.execute(
            "INSERT INTO tasks (text, created, due, place, repeat, goal) VALUES (?, ?, ?, ?, ?, ?)",
            (text, int(now or time.time()), due, place, int(repeat), goal),
        )
        self.db.commit()
        return cur.lastrowid

    def goals(self, day: str) -> list:
        """The goals set for a day, done or not, in the order they were given."""
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks WHERE goal = ? ORDER BY id", (day,))]

    def done_between(self, start: int, end: int) -> int:
        """How many tasks were finished from `start` up to `end`."""
        return self.db.execute("SELECT COUNT(*) FROM tasks WHERE done >= ? AND done < ?", (start, end)).fetchone()[0]

    def tasks(self, include_done: bool = False) -> list:
        where = "" if include_done else "WHERE done IS NULL"
        return [dict(row) for row in self.db.execute(f"SELECT * FROM tasks {where} ORDER BY done IS NOT NULL, due IS NULL, due, id")]

    def task(self, task_id: int):
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: int, **fields) -> None:
        allowed = {"text", "due", "place", "repeat", "done", "shown", "tries", "goal"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if fields:
            self.db.execute(f"UPDATE tasks SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", (*fields.values(), task_id))
            self.db.commit()

    def delete_task(self, task_id: int) -> None:
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.db.commit()

    def restore_task(self, task: dict) -> None:
        """Put back a task that was deleted, exactly as `task()` gave it before."""
        columns = ("id", "text", "created", "due", "place", "repeat", "done", "shown", "tries", "goal")
        self.db.execute(f"INSERT OR REPLACE INTO tasks ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", tuple(task.get(c) for c in columns))
        self.db.commit()

    def finished(self, since: int) -> list:
        """The tasks finished from `since` on, oldest first."""
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks WHERE done >= ? ORDER BY done", (since,))]

    def done_today(self, day_start: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tasks WHERE done >= ?", (day_start,)).fetchone()[0]

    # ------------------------------------------------------------------ what happened

    def log(self, kind: str, data=None, ts=None) -> None:
        self.db.execute("INSERT INTO events (ts, kind, data) VALUES (?, ?, ?)", (int(ts or time.time()), kind, json.dumps(data) if data is not None else None))
        self.db.commit()

    def events(self, kind: str, since: int = 0, until: int = FOREVER) -> list:
        rows = self.db.execute("SELECT ts, data FROM events WHERE kind = ? AND ts >= ? AND ts < ? ORDER BY ts", (kind, since, until))
        return [(row["ts"], json.loads(row["data"]) if row["data"] else None) for row in rows]

    def count(self, kind: str, since: int = 0, until: int = FOREVER) -> int:
        return self.db.execute("SELECT COUNT(*) FROM events WHERE kind = ? AND ts >= ? AND ts < ?", (kind, since, until)).fetchone()[0]

    # ------------------------------------------------------------------ "don't suggest this"

    def mute(self, key: str, until: int = FOREVER) -> None:
        self.db.execute("INSERT INTO mutes (key, until) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET until = excluded.until", (key, int(until)))
        self.db.commit()

    def unmute(self, key: str) -> None:
        self.db.execute("DELETE FROM mutes WHERE key = ?", (key,))
        self.db.commit()

    def muted(self, key: str, now=None) -> bool:
        row = self.db.execute("SELECT until FROM mutes WHERE key = ?", (key,)).fetchone()
        return bool(row) and row["until"] > int(now or time.time())

    def mutes(self, now=None) -> list:
        return [row["key"] for row in self.db.execute("SELECT key FROM mutes WHERE until > ? ORDER BY key", (int(now or time.time()),))]

    # ------------------------------------------------------------------ where you go next, and what you answer

    def add_move(self, src: str, dst: str) -> None:
        """You went from one place straight to another."""
        self.db.execute("INSERT INTO moves (src, dst, n) VALUES (?, ?, 1) ON CONFLICT (src, dst) DO UPDATE SET n = n + 1", (src, dst))
        self.db.commit()

    def moves_from(self, src: str) -> dict:
        return {row["dst"]: row["n"] for row in self.db.execute("SELECT dst, n FROM moves WHERE src = ?", (src,))}

    def answer(self, key: str, accepted: bool, now=None) -> dict:
        """Remember whether a suggestion was taken. Returns its record:
        yes and no counts, and `streak`, the refusals in a row."""
        now = int(now or time.time())
        if accepted:
            self.db.execute(
                "INSERT INTO feedback (key, yes, streak, last) VALUES (?, 1, 0, ?) "
                "ON CONFLICT (key) DO UPDATE SET yes = yes + 1, streak = 0, last = excluded.last", (key, now))
        else:
            self.db.execute(
                "INSERT INTO feedback (key, no, streak, last) VALUES (?, 1, 1, ?) "
                "ON CONFLICT (key) DO UPDATE SET no = no + 1, streak = streak + 1, last = excluded.last", (key, now))
        self.db.commit()
        return self.answers(key)

    def answers(self, key: str) -> dict:
        row = self.db.execute("SELECT * FROM feedback WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else dict(key=key, yes=0, no=0, streak=0, last=None)

    # ------------------------------------------------------------------ what the AI keeps in mind

    def notes(self) -> list:
        """Lasting things about you that the AI noted down, oldest first."""
        return [dict(row) for row in self.db.execute("SELECT * FROM memory ORDER BY id")]

    def add_note(self, text: str, now=None) -> int:
        """Keep a note. Returns its number, or 0 if there is nothing to keep or it is
        known already. Beyond NOTES_KEPT the oldest note makes room."""
        text = " ".join(str(text).split())[:NOTE_LENGTH]
        same = " ".join(text.lower().split())
        if not text or any(" ".join(note["text"].lower().split()) == same for note in self.notes()):
            return 0
        cur = self.db.execute("INSERT INTO memory (text, created) VALUES (?, ?)", (text, int(now or time.time())))
        self.db.execute("DELETE FROM memory WHERE id NOT IN (SELECT id FROM memory ORDER BY id DESC LIMIT ?)", (NOTES_KEPT,))
        self.db.commit()
        return cur.lastrowid

    def delete_note(self, note_id: int) -> None:
        self.db.execute("DELETE FROM memory WHERE id = ?", (note_id,))
        self.db.commit()

    def restore_note(self, note: dict) -> None:
        """Put back a note that was deleted, as `notes()` gave it before."""
        self.db.execute("INSERT OR REPLACE INTO memory (id, text, created) VALUES (?, ?, ?)", (note["id"], note["text"], note["created"]))
        self.db.commit()

    def clear_notes(self) -> None:
        self.db.execute("DELETE FROM memory")
        self.db.commit()

    def add_talk(self, language: str, role: str, content: str, shown: str, now=None) -> None:
        """One line of the conversation: `content` as the AI saw it, `shown` as the Chat
        window shows it. Only the last TALK_KEPT lines are kept."""
        self.db.execute("INSERT INTO talk (ts, language, role, content, shown) VALUES (?, ?, ?, ?, ?)", (int(now or time.time()), language, role, content, shown))
        self.db.execute("DELETE FROM talk WHERE id NOT IN (SELECT id FROM talk ORDER BY id DESC LIMIT ?)", (TALK_KEPT,))
        self.db.commit()

    def talk(self) -> list:
        return [dict(row) for row in self.db.execute("SELECT * FROM talk ORDER BY id")]

    def clear_talk(self) -> None:
        self.db.execute("DELETE FROM talk")
        self.db.commit()

    # ------------------------------------------------------------------ daily scripts

    def scripts(self) -> list:
        """What the person asked to have done every day, earliest first.

        name     what they call it                 text     what to do, in their own words
        at       minutes after midnight            days     which days (see EVERY_DAY)
        enabled  switched on                       acts     may do things by itself (else: it asks)
        look     a program to read first, if any   last     the day it last ran ("2026-11-13")"""
        return [dict(row) for row in self.db.execute("SELECT * FROM scripts ORDER BY at, id")]

    def script(self, script_id: int):
        row = self.db.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        return dict(row) if row else None

    def add_script(self, name: str, text: str, at: int, days: int = EVERY_DAY, acts: bool = False, look=None) -> int:
        """Returns the new script's number, or 0 if there are SCRIPTS_MOST already."""
        if len(self.scripts()) >= SCRIPTS_MOST:
            return 0
        cur = self.db.execute(
            "INSERT INTO scripts (name, text, at, days, acts, look) VALUES (?, ?, ?, ?, ?, ?)",
            (name, text, int(at) % 1440, int(days) & EVERY_DAY, int(bool(acts)), look or None),
        )
        self.db.commit()
        return cur.lastrowid

    def update_script(self, script_id: int, **fields) -> None:
        allowed = {"name", "text", "at", "days", "enabled", "acts", "look", "last"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if fields:
            self.db.execute(f"UPDATE scripts SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", (*fields.values(), script_id))
            self.db.commit()

    def delete_script(self, script_id: int) -> None:
        self.db.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
        self.db.commit()

    # ------------------------------------------------------------------ odds and ends

    # ------------------------------------------------------------------ habits, and goals for longer than a day

    def habits(self) -> list:
        return [dict(row) for row in self.db.execute("SELECT * FROM habits ORDER BY id")]

    def add_habit(self, name: str) -> int:
        cur = self.db.execute("INSERT INTO habits (name, created) VALUES (?, ?)", (name, int(time.time())))
        self.db.commit()
        return cur.lastrowid

    def delete_habit(self, habit: int) -> None:
        self.db.execute("DELETE FROM habits WHERE id = ?", (habit,))
        self.db.execute("DELETE FROM habit_days WHERE habit = ?", (habit,))
        self.db.commit()

    def habit_days(self, habit: int) -> set:
        """The days ("2026-11-13") on which a habit was kept."""
        return {row["day"] for row in self.db.execute("SELECT day FROM habit_days WHERE habit = ?", (habit,))}

    def mark_habit(self, habit: int, day: str, done: bool = True) -> None:
        if done:
            self.db.execute("INSERT OR IGNORE INTO habit_days (habit, day) VALUES (?, ?)", (habit, day))
        else:
            self.db.execute("DELETE FROM habit_days WHERE habit = ? AND day = ?", (habit, day))
        self.db.commit()

    def long_goals(self, span: str) -> list:
        """Goals for a "week", a "month" or a "year"; `period` says which one ("2026-W46", "2026-11", "2026")."""
        return [dict(row) for row in self.db.execute("SELECT * FROM goals WHERE span = ? ORDER BY id", (span,))]

    def add_long_goal(self, span: str, period: str, text: str) -> int:
        cur = self.db.execute("INSERT INTO goals (span, period, text) VALUES (?, ?, ?)", (span, period, text))
        self.db.commit()
        return cur.lastrowid

    def long_goal(self, goal: int):
        row = self.db.execute("SELECT * FROM goals WHERE id = ?", (goal,)).fetchone()
        return dict(row) if row else None

    def set_long_goal(self, goal: int, progress: int) -> None:
        """How far a goal has come, in per cent: 100 is done."""
        self.db.execute("UPDATE goals SET progress = ? WHERE id = ?", (max(0, min(100, int(progress))), goal))
        self.db.commit()

    def delete_long_goal(self, goal: int) -> None:
        self.db.execute("DELETE FROM goals WHERE id = ?", (goal,))
        self.db.commit()

    # ------------------------------------------------------------------ the person's own dates (birthdays and the like)

    def own_days(self) -> list:
        """Dates to be reminded of every year, in the order of the calendar."""
        return [dict(row) for row in self.db.execute("SELECT * FROM own_days ORDER BY month, day, id")]

    def add_own_day(self, name: str, month: int, day: int) -> int:
        cur = self.db.execute("INSERT INTO own_days (name, month, day) VALUES (?, ?, ?)", (name, min(max(int(month), 1), 12), min(max(int(day), 1), 31)))
        self.db.commit()
        return cur.lastrowid

    def delete_own_day(self, number: int) -> None:
        self.db.execute("DELETE FROM own_days WHERE id = ?", (number,))
        self.db.commit()

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def put(self, key: str, value) -> None:
        self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
        self.db.commit()

    def forget_learning(self) -> None:
        """Erase everything learned about you, the AI's notes and the conversation with
        it included. Tasks, settings and your bond stay."""
        bond = self.get("bond")
        for table in ("usage", "places", "plays", "events", "mutes", "kv", "moves", "feedback", "memory", "talk"):
            self.db.execute(f"DELETE FROM {table}")
        if bond is not None:
            self.put("bond", bond)
        self.put("mitti", True)  # not a thing learned: the cat is not renamed over this
        self.db.commit()
        self.db.execute("VACUUM")

    def close(self) -> None:
        try:
            self.db.commit()
            self.db.close()
        except sqlite3.Error:
            pass
