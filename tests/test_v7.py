"""Tests for what 0.7 added: the app's new name and what it takes over from the old one,
both AIs with the switch between them made by itself, daily scripts, renaming the cat.

The online AI is only ever a pretend service on this computer (the one in test_v4), and
"start with Windows" is tried on a registry key of the test's own.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import winreg
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v4 import Pretend  # noqa: E402
from test_v6 import Cat, FakeEngine, Host, answer  # noqa: E402
from workcat import APP_NAME, INSTANCE, OLD_NAME, assistant, autostart, cloud, store as store_module  # noqa: E402
from workcat import app as app_module  # noqa: E402
from workcat.ai import AI  # noqa: E402
from workcat.store import Store  # noqa: E402


class NameTest(unittest.TestCase):
    """The app is called MyCat; what a version called WorkCat left behind is taken over."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.was = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.folder.name
        self.base = Path(self.folder.name)

    def tearDown(self):
        if self.was is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.was
        self.folder.cleanup()

    def test_the_names(self):
        self.assertEqual((APP_NAME, OLD_NAME, INSTANCE), ("MyCat", "WorkCat", "WorkCat"))
        self.assertEqual(app_module.instance_name(store_module.default_folder()), "WorkCat")  # a running older cat is found by it
        self.assertRegex(app_module.instance_name(self.base / "elsewhere"), r"^WorkCat-[0-9a-f]{12}$")

    def test_a_new_computer_gets_a_folder_of_the_new_name(self):
        self.assertEqual(store_module.default_folder(), self.base / "MyCat")
        self.assertFalse(store_module.adopt_old_folder())  # nothing to take over
        self.assertEqual(list(self.base.iterdir()), [])  # and looking made nothing

    def test_the_old_folder_is_used_and_then_renamed_with_all_that_is_in_it(self):
        old = self.base / "WorkCat"
        (old / "ai" / "models").mkdir(parents=True)
        (old / "settings.json").write_text(json.dumps({"name": "Barsik", "first_run_done": True}), encoding="utf-8")
        (old / "ai" / "models" / "big.bin").write_bytes(b"x" * 1000)
        self.assertEqual(store_module.default_folder(), old)  # looking does not move it: tools and tests may look
        self.assertTrue(old.is_dir())
        self.assertTrue(store_module.adopt_old_folder())
        new = self.base / "MyCat"
        self.assertEqual(store_module.default_folder(), new)
        self.assertFalse(old.exists())
        self.assertEqual((new / "ai" / "models" / "big.bin").stat().st_size, 1000)
        store = Store(new)
        self.assertEqual(store.settings["name"], "Barsik")
        store.close()
        self.assertFalse(store_module.adopt_old_folder())  # once

    def test_a_folder_in_use_stays_where_it_is_until_it_is_free(self):
        old = self.base / "WorkCat"
        old.mkdir()
        held = open(old / "workcat.db", "wb")  # as while an older cat still runs
        try:
            self.assertFalse(store_module.adopt_old_folder())
            self.assertEqual(store_module.default_folder(), old)  # the cat goes on with it there
        finally:
            held.close()
        self.assertTrue(store_module.adopt_old_folder())  # at a later start
        self.assertEqual(store_module.default_folder(), self.base / "MyCat")

    def test_both_folders_there_the_new_one_counts(self):
        (self.base / "WorkCat").mkdir()
        (self.base / "MyCat").mkdir()
        self.assertEqual(store_module.default_folder(), self.base / "MyCat")
        self.assertFalse(store_module.adopt_old_folder())
        self.assertTrue((self.base / "WorkCat").is_dir())  # nothing is ever written over


class AutostartTest(unittest.TestCase):
    KEY = r"Software\MyCat-test-run"

    def setUp(self):
        self.real, autostart.RUN_KEY = autostart.RUN_KEY, self.KEY
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY).Close()

    def tearDown(self):
        autostart.RUN_KEY = self.real
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.KEY)

    def values(self) -> dict:
        found, at = {}, 0
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, at)
                except OSError:
                    return found
                found[name] = value
                at += 1

    def test_on_and_off_under_the_new_name(self):
        self.assertFalse(autostart.enabled())
        self.assertTrue(autostart.set_enabled(True))
        self.assertEqual(list(self.values()), ["MyCat"])
        self.assertIn("MyCat.pyw", self.values()["MyCat"])
        self.assertTrue(autostart.enabled())
        self.assertTrue(autostart.set_enabled(False))
        self.assertEqual(self.values(), {})

    def test_an_entry_of_the_old_name_is_taken_over(self):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "WorkCat", 0, winreg.REG_SZ, r'"C:\gone\WorkCat.exe"')
        self.assertTrue(autostart.enabled())  # it was wanted: that still counts
        self.assertTrue(autostart.adopt_old_value())
        self.assertEqual(list(self.values()), ["MyCat"])  # under the new name, pointing at this copy
        self.assertNotIn("gone", self.values()["MyCat"])
        self.assertFalse(autostart.adopt_old_value())  # once
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "WorkCat", 0, winreg.REG_SZ, "x")
        self.assertTrue(autostart.set_enabled(False))  # switched off: both are gone
        self.assertEqual(self.values(), {})


class SourceTest(unittest.TestCase):
    def test_the_old_switch_becomes_the_choice_both(self):
        for saved, expected in (
            ({"ai_source": "online", "ai_fallback": True}, "both"),
            ({"ai_source": "online", "ai_fallback": False}, "online"),
            ({"ai_source": "offline", "ai_fallback": True}, "offline"),
            ({"ai_source": "online"}, "online"),  # written by this version: nothing to carry over
            ({"ai_source": "both"}, "both"),
        ):
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder) / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
                store = Store(Path(folder))
                self.assertEqual(store.settings["ai_source"], expected, saved)
                self.assertNotIn("ai_fallback", store.settings)
                store.save_settings()
                store.close()
                again = Store(Path(folder))  # and it stays what it became
                self.assertEqual(again.settings["ai_source"], expected, saved)
                again.close()


class BothTest(unittest.TestCase):
    """Online while it can be reached, this computer when it cannot: there and back by itself."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pretend)
        cls.address = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.sleep, cloud.time.sleep = cloud.time.sleep, lambda seconds: None

    @classmethod
    def tearDownClass(cls):
        cloud.time.sleep = cls.sleep
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Pretend.seen, Pretend.answer_with, Pretend.message, Pretend.no_json_mode = [], [], "nope", False
        Pretend.models = ["b-model", "models/a-model"]
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.host = Host(self.store)
        self.engine = FakeEngine(["gemma3:4b"])
        self.ai = AI(self.host, self.engine)
        self.heard = []
        self.ai.listeners.append(lambda what, payload: self.heard.append((what, payload)))

    def tearDown(self):
        self.engine.gate.set()
        self.store.close()
        self.folder.cleanup()

    def choose(self, source: str, address: str = "", key: bool = True) -> None:
        self.host.settings.update(ai_source=source, ai_service="other", ai_address=address or self.address, ai_online_model="some-model", ai_key=cloud.lock("sk-test-not-a-real-key") if key else "")
        self.ai.settle()

    def pump(self, until, seconds: float = 10.0) -> None:
        import queue

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                _kind, payload = self.host.inbox.get(timeout=0.05)
            except queue.Empty:
                continue
            self.ai.handle(*payload)
            if until():
                return
        self.fail(f"waited in vain; heard {[what for what, _ in self.heard]}")

    def said(self, what: str):
        return [payload for heard, payload in self.heard if heard == what]

    def ask(self) -> tuple:
        self.heard.clear()
        self.assertTrue(self.ai.ask("hello there, how are you?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("answer") or self.said("error"))
        return self.said("answer")[0] if self.said("answer") else (None, self.said("error"))

    def test_the_door_of_a_service(self):
        self.assertTrue(cloud.Online("other", "k", "m", self.address).knock())
        started = time.monotonic()
        self.assertFalse(cloud.Online("other", "k", "m", "http://127.0.0.1:1").knock(1.0))
        self.assertLess(time.monotonic() - started, 4)  # seconds, not a minute
        self.assertFalse(cloud.Online("other", "k", "m", "").knock())

    def test_either_half_alone_answers(self):
        self.choose("both")
        self.assertEqual((self.ai.state, self.ai.both, self.ai.online, self.ai.model_name), ("ready", True, True, "some-model"))
        self.choose("both", key=False)  # no key yet: this computer answers
        self.assertEqual((self.ai.state, self.ai.brain is self.engine, self.ai.model_name), ("ready", True, "gemma3:4b"))
        self.assertEqual(self.ask()[0], "from this computer")
        self.assertEqual(Pretend.seen, [])
        self.engine.have.clear()  # no AI on this computer: the online one answers
        self.choose("both")
        self.assertEqual((self.ai.state, self.ai.brain is self.engine), ("ready", False))
        self.assertEqual(self.ask()[0], "Hello there")
        self.choose("both", key=False)  # neither: nothing to ask
        self.assertEqual(self.ai.state, "missing")
        self.assertFalse(self.ai.ask("hello", ("LASTING", "NOW")))
        self.assertFalse(self.ai.busy)

    def test_online_while_it_is_there(self):
        self.choose("both")
        reply, notes = self.ask()
        self.assertEqual((reply, notes, self.engine.asked), ("Hello there", [], []))
        self.assertEqual(self.ai.answered, {"local": False, "down": False})

    def test_it_switches_by_itself_and_back(self):
        self.choose("both")
        service = self.ai.service()
        service.knock = lambda timeout=2.0: False  # the connection is gone
        reply, notes = self.ask()
        self.assertEqual(reply, "from this computer")
        self.assertEqual(notes[0]["mark"], "!")
        self.assertIn("No connection to the online service", notes[0]["text"])
        self.assertEqual(Pretend.seen, [])  # the question itself was not sent into the void
        self.assertTrue(self.ai.online_down())
        self.assertEqual(self.ai.answered, {"local": True, "down": True})
        self.assertIs(self.ai.brain, self.engine)

        reply, notes = self.ask()  # a moment later: straight to this computer, and without saying it again
        self.assertEqual((reply, notes), ("from this computer", []))
        self.assertEqual(self.said("switched"), [])
        self.assertEqual(self.ai.answered["down"], True)

        service.knock = lambda timeout=2.0: True  # the connection is back, which the cat does not know yet
        self.assertTrue(self.ai.online_down())
        self.ai.last_watch = 0.0
        self.heard.clear()
        self.ai.watch()  # the look it takes once a minute
        self.pump(lambda: self.said("state"))
        self.assertFalse(self.ai.online_down())
        reply, notes = self.ask()
        self.assertEqual((reply, notes), ("Hello there", []))
        self.assertEqual(self.ai.answered, {"local": False, "down": False})

    def test_a_dead_address_is_found_out_in_seconds(self):
        self.choose("both", address="http://127.0.0.1:1")
        started = time.monotonic()
        reply, _notes = self.ask()
        self.assertEqual(reply, "from this computer")
        self.assertLess(time.monotonic() - started, 6)
        started = time.monotonic()
        self.assertEqual(self.ask()[0], "from this computer")  # and the next one does not wait at all
        self.assertLess(time.monotonic() - started, 1.5)
        self.choose("both")  # another address: what was out of reach before says nothing about this one
        self.assertEqual(self.ask()[0], "Hello there")

    def test_the_minute_passes_and_online_is_tried_again(self):
        self.choose("both", address="http://127.0.0.1:1")
        self.ask()
        self.assertTrue(self.ai.online_down())
        self.choose("both")
        self.ai.down_until = time.monotonic() - 1  # a minute later
        self.assertEqual(self.ask()[0], "Hello there")

    def test_another_kind_of_failure_switches_too(self):
        self.choose("both")
        Pretend.answer_with, Pretend.message = [401], "bad key"
        reply, notes = self.ask()
        self.assertEqual(reply, "from this computer")
        self.assertIn("The service did not accept the key", notes[0]["text"])

    def test_online_only_never_falls_back(self):
        self.choose("online", address="http://127.0.0.1:1")
        reply, errors = self.ask()
        self.assertIsNone(reply)
        self.assertEqual(errors, ["No connection to the online service. Is the internet working, and is the address right?"])
        self.assertEqual(self.engine.asked, [])

    def test_the_watch_keeps_to_itself_unless_both_is_chosen(self):
        for source in ("offline", "online"):
            self.choose(source)
            self.ai.last_watch = 0.0
            self.ai.watch()
            self.assertFalse(self.ai.watching, source)
        self.choose("both", address="http://127.0.0.1:1")
        self.ai.last_watch = 0.0
        self.heard.clear()
        self.ai.watch()
        self.assertTrue(self.ai.watching)
        self.ai.watch()  # one look at a time
        self.pump(lambda: self.said("state"))
        self.assertTrue(self.ai.online_down())
        self.assertFalse(self.ai.watching)

    def test_each_half_can_be_tested(self):
        self.choose("both")
        self.ai.test("online")
        self.pump(lambda: self.said("tested"))
        self.assertEqual(self.said("tested")[0][1]["model"], "some-model")
        self.heard.clear()
        self.ai.test("offline")
        self.pump(lambda: self.said("tested"))
        self.assertEqual(self.said("tested")[0][1]["model"], "gemma3:4b")


class Scripted(Cat):
    """The cat of test_v6, with what daily scripts need."""

    scripts_due = app_module.App.scripts_due
    run_script = app_module.App.run_script
    asks_first = app_module.App.asks_first
    rename_cat = app_module.App.rename_cat
    may_read = app_module.App.may_read
    read_name = app_module.App.read_name

    def __init__(self, store):
        super().__init__(store)
        self.script_now, self.last_idle, self.in_call, self.quiet = None, 0.0, False, ""
        self.asked, self.spoken, self.panel, self.looked = [], [], None, []
        self.focus = type("Focus", (), {"focusing": False})()
        self.voice = type("Voice", (), {"say": lambda _self, text, buttons=(), **kind: self.spoken.append(text)})()

    def quiet_level(self) -> str:
        return self.quiet

    def ask_ai(self, text: str, source: str = "window", look: int = 0) -> bool:
        self.asked.append((text, source))
        self.looked.append(look)
        return self.ai.state == "ready" and not self.ai.busy

    def apply_settings(self) -> None:
        self.store.save_settings()


class ScriptsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.cat = Scripted(self.store)
        self.day = dt.date.fromisoformat(self.cat.today)

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def at(self, hour: int, minute: int = 0) -> float:
        return dt.datetime.combine(self.day, dt.time(hour, minute)).timestamp()

    def test_scripts_are_kept(self):
        store = self.store
        late = store.add_script("Evening review", "Tell me what is left.", 18 * 60, store_module.WORKDAYS)
        early = store.add_script("Morning briefing", "Three things for today.", 9 * 60, acts=True)
        self.assertEqual([script["name"] for script in store.scripts()], ["Morning briefing", "Evening review"])  # earliest first
        first = store.script(early)
        self.assertEqual((first["at"], first["days"], first["enabled"], first["acts"], first["last"]), (540, 127, 1, 1, None))
        store.update_script(late, enabled=0, at=17 * 60, name="Review", nonsense=1)
        self.assertEqual((store.script(late)["enabled"], store.script(late)["at"], store.script(late)["name"]), (0, 1020, "Review"))
        store.delete_script(early)
        self.assertEqual(len(store.scripts()), 1)
        for i in range(store_module.SCRIPTS_MOST + 3):
            store.add_script(f"S{i}", "x", 60)
        self.assertEqual(len(store.scripts()), store_module.SCRIPTS_MOST)
        store.forget_learning()  # what was learned goes; what the person wrote stays
        self.assertEqual(len(store.scripts()), store_module.SCRIPTS_MOST)

    def test_a_script_runs_at_its_time_once_a_day(self):
        number = self.store.add_script("Morning briefing", "Three things for today.", 9 * 60)
        self.assertFalse(self.cat.scripts_due(self.at(8, 59)))
        self.assertTrue(self.cat.scripts_due(self.at(9, 0)))
        self.assertEqual(self.cat.asked, [("Three things for today.", "script")])
        self.assertEqual((self.cat.script_now["id"], self.store.script(number)["last"]), (number, self.cat.today))
        self.assertFalse(self.cat.scripts_due(self.at(9, 1)))  # it is running
        self.cat.script_now = None
        self.assertFalse(self.cat.scripts_due(self.at(15, 0)))  # and has had its turn today
        self.assertEqual(len(self.cat.asked), 1)

    def test_a_computer_switched_on_late_catches_up(self):
        self.store.add_script("Morning briefing", "Three things for today.", 9 * 60)
        self.assertTrue(self.cat.scripts_due(self.at(13, 30)))

    def test_only_on_its_days_and_only_when_switched_on(self):
        today = 1 << self.day.weekday()
        other = self.store.add_script("Another day", "x", 9 * 60, days=store_module.EVERY_DAY & ~today)
        off = self.store.add_script("Off", "y", 9 * 60)
        self.store.update_script(off, enabled=0)
        self.assertFalse(self.cat.scripts_due(self.at(10, 0)))
        self.store.update_script(other, days=today)
        self.assertTrue(self.cat.scripts_due(self.at(10, 0)))

    def test_it_waits_until_the_person_is_there_and_free(self):
        self.store.add_script("Morning briefing", "x", 9 * 60)
        now = self.at(10, 0)
        for hinder, undo in (
            (lambda: setattr(self.cat, "last_idle", 600.0), lambda: setattr(self.cat, "last_idle", 0.0)),  # away from the keyboard
            (lambda: setattr(self.cat, "quiet", "hard"), lambda: setattr(self.cat, "quiet", "")),  # something full screen, or the cat hidden
            (lambda: setattr(self.cat.focus, "focusing", True), lambda: setattr(self.cat.focus, "focusing", False)),
            (lambda: setattr(self.cat, "in_call", True), lambda: setattr(self.cat, "in_call", False)),
            (lambda: setattr(self.cat.ai, "busy", True), lambda: setattr(self.cat.ai, "busy", False)),
        ):
            hinder()
            self.assertFalse(self.cat.scripts_due(now))
            undo()
        self.assertEqual(self.cat.asked, [])
        self.cat.quiet = "soft"  # tucked away at the side: what was asked for still comes
        self.assertTrue(self.cat.scripts_due(now))

    def test_without_an_ai_it_says_so_once_and_runs_when_there_is_one(self):
        number = self.store.add_script("Morning briefing", "x", 9 * 60)
        self.cat.ai.state = "missing"
        self.assertFalse(self.cat.scripts_due(self.at(9, 0)))
        self.assertFalse(self.cat.scripts_due(self.at(9, 1)))
        self.assertEqual(self.cat.spoken, ['I could not run "Morning briefing": my AI brain is not ready.'])  # once, not every half minute
        self.assertIsNone(self.store.script(number)["last"])  # its turn is still to come
        self.cat.ai.state = "ready"
        self.assertTrue(self.cat.scripts_due(self.at(9, 2)))

    def test_run_now_is_a_try_not_todays_run(self):
        number = self.store.add_script("Evening review", "x", 18 * 60)
        self.assertTrue(self.cat.run_script(self.store.script(number), by_hand=True))
        self.assertIsNone(self.store.script(number)["last"])
        self.assertFalse(self.cat.run_script(self.store.script(number), by_hand=True))  # one at a time
        self.assertEqual(self.cat.spoken, ["One moment, I am still answering."])

    def test_a_script_acts_by_itself_only_if_it_may(self):
        report = self.store.add_task("Send the report")
        actions = [{"do": "done", "task": report}]
        asking = self.store.add_script("Asks", "x", 60)
        acting = self.store.add_script("Acts", "y", 61, acts=True)
        self.cat.script_now = self.store.script(asking)
        self.assertTrue(self.cat.asks_first())
        notes = self.cat.run_ai_actions(actions, None)
        self.assertEqual([(note["mark"], note["text"]) for note in notes], [("?", "Tick off: Send the report?")])
        self.assertIsNone(self.store.task(report)["done"])  # it waits for the click
        self.cat.script_now = self.store.script(acting)
        self.assertFalse(self.cat.asks_first())
        notes = self.cat.run_ai_actions(actions, None)
        self.assertEqual(notes[0]["text"], "Finished: Send the report")
        self.cat.script_now = None  # an ordinary question: as the person set it for everything
        self.assertFalse(self.cat.asks_first())
        self.cat.settings["ai_ask_first"] = True
        self.cat.script_now = self.store.script(acting)
        self.assertTrue(self.cat.asks_first())  # "ask me first" for everything holds for scripts too

    def test_the_model_is_told_when_it_must_ask(self):
        lasting, _ = assistant.system_prompt("Mitti", "Content", "why", 25, "", ask_first=True)
        self.assertIn("confirms each action with a button", lasting)

    def test_the_cat_takes_another_name(self):
        self.cat.rename_cat("  Barsik   the  Second, of  his  name ")
        self.assertEqual(self.cat.settings["name"], "Barsik the Second, o")  # tidied, and no longer than fits
        self.assertEqual(self.cat.spoken, ["Barsik the Second, o! I like it. That is my name from now on."])
        self.cat.rename_cat("   ")  # no name is no name
        self.cat.rename_cat("Barsik the Second, o")  # the same again: nothing to say
        self.assertEqual((self.cat.settings["name"], len(self.cat.spoken)), ("Barsik the Second, o", 1))
        self.assertEqual(json.loads(self.store.settings_path.read_text(encoding="utf-8"))["name"], "Barsik the Second, o")


class SmallModelTest(unittest.TestCase):
    """What the real Small model did on 2026-11-13, each as it came back, and what the
    app makes of it now."""

    TASKS = {4: "Send the weekly report", 7: "Call the bank", 9: "Water the plants", 12: "Купить молоко", 15: "Hisobotni tekshirish"}

    def result(self, said: str, careful: bool = True, **filled):
        turn = assistant.Talk().turn(said, careful=careful)
        turn.tasks = dict(self.TASKS)
        turn.notes = {2: "The user works as an accountant."}
        return turn.result(json.dumps({**assistant._EMPTY, "reply": "ok", **filled}), list(self.TASKS.values()))

    def test_no_reminder_that_nobody_asked_for(self):
        five = {"when": "17:00"}
        for said, reminder, left in (
            ("What is on my list?", "Send the weekly report", []),  # on the list already, and a question
            ("What is on my list?", "Send report", []),  # the same in other words: not what the message is about
            ("Я купил молоко", "Я купил молоко", [{"do": "offer", "task": 12}]),  # the message itself, as a reminder
            ("Запомни, что мой руководитель Азиз", "Отправьте отчет по неделе", [{"do": "remember", "text": "Мой руководитель Азиз"}]),
            ("Hisobotni tekshirishni ertaga soat 9 ga ko'chir", "Hisobotni tekshirishni ertaga soat 9 ga ko'chir", [{"do": "nothing"}]),  # and it is told that the task was not moved
            ("How is my day going?", "Send the weekly report", []),
            ("Бугун нима қилишим керак?", "Ҳисоботни юбориш", []),
        ):
            self.assertEqual(self.result(said, reminders=[{"text": reminder, **five}])[1], left, said)

    def test_a_reminder_that_was_asked_for_is_made(self):
        for said, reminder, kept in (
            ("Remind me to ring mum at 6", "Call mom", "Call mom"),  # asked in as many words: the model's wording stands
            ("Add milk to my list", "Milk", "Milk"),
            ("Remind me to call the bank at 5", "Call the bank", "Call the bank"),  # also when it is on the list already: now with a time
            ("Don't forget to call Aziz tomorrow at 9", "Call Aziz", "Call Aziz"),  # may be asking: and the reminder is about the message
            ("I need to send the invoice by Friday", "Send the invoice", "Send the invoice"),
            ("Remember to call Aziz at 9", "Call Aziz", "Call Aziz"),
            ("Мне нужно позвонить в банк завтра", "Позвонить в банк", "Позвонить в банк"),
            ("Напомни позвонить Азизу завтра в 9", "Call Aziz", "Напомни позвонить Азизу завтра в 9"),  # another language: their own words
            ("Эртага соат 10 да ҳисобот юборишни эслатиб қўй", "Hisobot yuborish", "Ҳисобот юбориш"),
            ("Sut olishni ro'yxatga qo'shib qo'y", "Sut olish", "Sut olish"),
        ):
            actions = self.result(said, reminders=[{"text": reminder, "when": "tomorrow 09:00"}])[1]
            self.assertEqual([(a["do"], a.get("text")) for a in actions], [("remind", kept)], said)
        self.assertEqual(self.result("Qo'shiq tavsiya qil", reminders=[{"text": "Qo'shiq", "when": ""}])[1], [])  # "qo'shiq" is a song, not "add"

    def test_a_big_model_is_judged_as_before(self):
        asked = self.result("What do I need to do today?", careful=False, reminders=[{"text": "Send the weekly report", "when": "17:00"}])[1]
        self.assertEqual(asked, [])  # on the list already, and no reminder was asked for
        new = self.result("What do I need to do today?", careful=False, reminders=[{"text": "Stretch", "when": "15:00"}])[1]
        self.assertEqual([a["do"] for a in new], ["remind"])
        translated = self.result("Translate to Russian: the weekly report is ready", careful=False, done=[4])[1]
        self.assertEqual(translated, [{"do": "done", "task": 4}])

    def test_a_text_to_work_on_is_not_a_wish(self):
        for said in (
            "Translate to Russian: Good morning, the report is ready.",
            "Make this shorter: I finished the weekly report and called the bank",
            "Переведи на английский: «Я купил молоко»",
            "Исправь ошибки: я отправил отчет и полил цветы",
            'Fix the grammar in "I has sent the weekly report"',
            "Буни рус тилига таржима қил: ҳисоботни текширдим",
        ):
            actions = self.result(said, done=[4, 12, 15], open=["Excel"], reminders=[{"text": "Report", "when": "17:00"}], remember=["The report is ready."])[1]
            self.assertEqual(actions, [], said)
        for said, do in (  # a colon alone makes no text to work on
            ("My goals for today: the weekly report and the bank call", "goals"),
            ("Remind me at 5: correct the invoice", "remind"),
        ):
            actions = self.result(said, goals=["The weekly report", "The bank call"], reminders=[{"text": "Correct the invoice", "when": "17:00"}])[1]
            self.assertIn(do, [a["do"] for a in actions], said)

    def test_what_was_dictated_is_noted_when_the_model_only_answered(self):
        for said, kept in (
            ("Запомни, что мой руководитель Азиз", "Мой руководитель Азиз"),
            ("Эслаб қол: мен банкда ишлайман", "Мен банкда ишлайман"),
            ("Please remember that I leave at six on Fridays", "I leave at six on Fridays"),
            ("Men bankda ishlayman, eslab qol", "Men bankda ishlayman"),
        ):
            self.assertEqual(self.result(said)[1], [{"do": "remember", "text": kept}], said)
        for said in (
            "Remember to call Aziz at 9",  # that asks for a reminder; none came, so nothing is made up
            "Do you remember that Aziz is my manager?", "I can't remember the name of that song", "Запомнил?",
        ):
            self.assertEqual(self.result(said)[1], [], said)
        self.assertEqual(self.result("Запомни, что мой руководитель Азиз", careful=False)[1], [])  # a big model is not second-guessed
        opened = self.result("Запомни, что мой руководитель Азиз и открой Excel", open=["Excel"])[1]
        self.assertEqual(opened, [{"do": "open", "name": "Excel"}])  # only when the model did nothing at all

    def test_a_reply_that_goes_round_in_circles_ends_there(self):
        loop = "Men o'tiringam. " * 60 + "Men o"
        self.assertEqual(assistant.unlooped(loop), "Men o'tiringam.")
        real = "Ўтинч, қандай қўшган ўтинч? Қандай қўшган? Мизинни қандай қўшган? " + "Қандай қўшган? " * 40
        self.assertEqual(assistant.unlooped(real), "Ўтинч, қандай қўшган ўтинч? Қандай қўшган? Мизинни қандай қўшган? Қандай қўшган?")
        self.assertEqual(assistant.unlooped("Good. " + "First this. Then that. " * 5), "Good. First this. Then that.")
        self.assertEqual(assistant.unlooped("Yes, " + "very " * 30 + "good."), "Yes, very")
        self.assertEqual(assistant.unlooped("One\n" + "- the same line\n" * 8), "One\n- the same line")
        for fine in (
            "No. No. Yes, all right.", "Ha ha ha, good one!", "Go! Go! Go! You can do it.", "Step 1. Open Excel. Step 2. Open the file. Step 3. Save it.",
            "1. Report\n2. Bank\n3. Plants", "It is 5. It is 5 o'clock, really.", "Да. Да. Сделаю.",
            "Thank you for the invoice. I have checked it. " * 3 + "Kind regards",  # said three times is still somebody's letter
        ):
            self.assertEqual(assistant.unlooped(fine), fine)
        turn = assistant.Talk().turn("Hozir nima qilay?")
        self.assertEqual(turn.live("Men o'tiringam. " * 9), "Men o'tiringam.")  # nor while it is still being written
        self.assertEqual(turn.result(json.dumps({**assistant._EMPTY, "reply": loop}))[0], "Men o'tiringam.")
        big = assistant.Talk().turn("Write it out ten times: I will not be late.", careful=False)
        lines = "I will not be late. " * 10
        self.assertEqual(big.result(json.dumps({**assistant._EMPTY, "reply": lines}))[0], lines.strip())  # a big model does not get stuck: its words stand
        self.assertEqual(big.live(lines), lines)

    def test_thanks_starts_no_timer_and_a_moment_opens_nothing(self):
        """From the real Better model: it repeated the focus round of two messages
        earlier after "Спасибо!", and opened Excel for "... when I open Excel"."""
        for said in ("Спасибо!", "Thanks!", "Rahmat, yaxshi!", "How are you?", "Что у меня в списке?"):
            self.assertEqual(self.result(said, focus_minutes=30)[1], [], said)
            self.assertEqual(self.result(said, start_break=True)[1], [], said)
        for said in ("Начни фокус на 30 минут", "Let's focus", "Start the timer", "25 minutes of deep work", "Фокусни бошла", "Diqqatni jamlashim kerak"):
            self.assertEqual(self.result(said, focus_minutes=30)[1], [{"do": "focus", "minutes": 30}], said)
        for said in ("I need a break", "Сделаем перерыв", "Tanaffus qilaylik", "Я устал"):
            self.assertEqual(self.result(said, start_break=True)[1], [{"do": "break"}], said)
        self.assertEqual(self.result("Спасибо!", careful=False, focus_minutes=30)[1], [{"do": "focus", "minutes": 30}])  # a big model is taken at its word

        for said in (
            "Excel'ни очганимда ҳисоботни сақлашни эслат", "Remind me to save the report when I open Excel",
            "Напомни сохранить отчёт, когда я открою Excel", "Excel'ni ochganimda hisobotni saqlashni eslat",
        ):
            actions = self.result(said, reminders=[{"text": "Save the report", "when": ""}], open=["Excel"])[1]
            self.assertEqual([a["do"] for a in actions], ["remind"], said)
        for said in ("Open Excel", "Excel'ни оч", "Открой Excel", "Open Chrome when I open Excel, no, open it now"):
            self.assertIn("open", [a["do"] for a in self.result(said, open=["Excel"])[1]], said)

    def test_said_but_not_done_is_offered_or_owned_up_to(self):
        """The real Small model: "Удали задачу про молоко" -> "Задача про молоко удалена."
        and an empty list. And asked to move a task, some words and nothing else."""
        self.assertEqual(self.result("Удали задачу про молоко")[1], [{"do": "offer", "task": 12, "what": "remove"}])
        self.assertEqual(self.result("Delete the plants task", done=[4], remove=[4])[1], [{"do": "offer", "task": 9, "what": "remove"}])  # it named another task: not that one
        self.assertEqual(self.result("Delete task 7")[1], [{"do": "offer", "task": 7, "what": "remove"}])
        self.assertEqual(self.result("Hisobotni tekshirishni ertaga soat 9 ga ko'chir")[1], [{"do": "nothing"}])
        self.assertEqual(self.result("Move the bank call to tomorrow at 11")[1], [{"do": "nothing"}])
        for said, wished in (("Мне нужно купить молоко", {"remove": [12]}), ("Open Dropbox", {"remove": [4]})):
            self.assertEqual(self.result(said, **wished)[1], [], said)  # "мне нужно" is not "не нужно", nor Dropbox a "drop"
        for said in ("Delete everything", "Should I delete the plants task?", "How do I move a window?", "Thanks, that is all for later"):
            self.assertEqual(self.result(said)[1], [], said)  # no task is named, or it is a question
        self.assertEqual(self.result("Open Excel and move the bank call to later", open=["Excel"])[1], [{"do": "open", "name": "Excel"}])  # something was done: no "nothing"
        self.assertEqual(self.result("Удали задачу про молоко", careful=False)[1], [])  # a big model is not second-guessed
        done = self.result("Удали задачу про молоко", remove=[12])[1]
        self.assertEqual(done, [{"do": "remove", "task": 12}])  # where the model did its part, nothing is offered on top

    def test_brackets_left_after_the_last_word_go(self):
        self.assertEqual(assistant.parse(answer(reply="Soat 10 da yoki keyin. }}"))[0], "Soat 10 da yoki keyin.")
        self.assertEqual(assistant.parse(answer(reply="See note [2]"))[0], "See note [2]")  # brackets that belong to the sentence stay

    def test_what_a_search_will_find_is_not_made_up(self):
        made_up = "Okay, searching for flights to Tashkent... Here are a few options:\n\n* Turkish Airlines: $600-$800.\n* Qatar Airways: $700-$900."
        reply, actions = self.result("Search the web for flights to Tashkent", reply=made_up, search="flights to Tashkent")
        self.assertEqual((reply, actions), ("Okay, searching for flights to Tashkent...", [{"do": "search", "query": "flights to Tashkent"}]))
        short = "Searching for flights to Tashkent now. Please wait..."
        self.assertEqual(self.result("Search the web for flights to Tashkent", reply=short, search="flights to Tashkent")[0], short)
        self.assertEqual(self.result("Search the web for flights to Tashkent", reply="Sure! " + made_up, search="flights to Tashkent")[0], "Sure! Okay, searching for flights to Tashkent...")
        self.assertEqual(self.result("Search the web for flights to Tashkent", careful=False, reply=made_up, search="flights to Tashkent")[0], made_up)
        self.assertEqual(self.result("Plan my day", reply=made_up)[0], made_up)  # no search: the reply is the answer


if __name__ == "__main__":
    unittest.main()
