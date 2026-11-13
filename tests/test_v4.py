"""What came with version 0.4: shortcut keys, tucking away at a screen edge, the sounds,
goals and the week, and the online AI (against a stand-in service on this computer:
nothing here reaches the internet).

    python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workcat import advisor, assistant, brain, cloud, hotkeys, llm, mood, sounds, world  # noqa: E402
from workcat.store import Store  # noqa: E402
from workcat.win32 import Monitor, Rect  # noqa: E402


class ShortcutKeysTest(unittest.TestCase):
    def test_reading_and_spelling(self):
        self.assertEqual(hotkeys.parse("Ctrl+Alt+H"), (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, 0x48))
        self.assertEqual(hotkeys.parse("ctrl + alt + space"), (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, 0x20))
        self.assertEqual(hotkeys.parse("Win+Shift+F9"), (hotkeys.MOD_WIN | hotkeys.MOD_SHIFT, 0x78))
        self.assertEqual(hotkeys.tidy("alt+ctrl+h"), "Ctrl+Alt+H")  # one true spelling, whatever the order typed
        self.assertEqual(hotkeys.tidy("Control+Shift+pagedown"), "Ctrl+Shift+PageDown")
        self.assertEqual(hotkeys.spell(*hotkeys.parse("Ctrl+Alt+7")), "Ctrl+Alt+7")

    def test_what_is_not_a_usable_shortcut(self):
        for bad in ("", "H", "Shift+H", "Ctrl", "Ctrl+Alt", "Ctrl+H+J", "Ctrl+Hello", "Ctrl++H", None):
            self.assertIsNone(hotkeys.parse(bad), bad)  # a bare key or Shift alone would take a letter away from typing
            self.assertEqual(hotkeys.tidy(bad), "")

    def test_a_key_press_in_the_settings_field(self):
        control, alt, shift = 0x0004, 0x20000, 0x0001
        self.assertEqual(hotkeys.pressed(control | alt, 0x48), "Ctrl+Alt+H")
        self.assertEqual(hotkeys.pressed(control | shift, 0x20), "Ctrl+Shift+Space")
        self.assertEqual(hotkeys.pressed(control | alt, 0x11), "")  # only Ctrl itself so far
        self.assertEqual(hotkeys.pressed(0, 0x48), "")
        self.assertEqual(hotkeys.pressed(shift, 0x48), "")

    def test_saved_keys_are_merged_with_the_usual_ones(self):
        self.assertEqual(hotkeys.merged({}), hotkeys.DEFAULTS)
        self.assertEqual(hotkeys.merged(None), hotkeys.DEFAULTS)
        mine = hotkeys.merged({"ask": "ctrl+alt+a", "focus": "", "task": "nonsense", "other": "Ctrl+Alt+O"})
        self.assertEqual(mine["ask"], "Ctrl+Alt+A")
        self.assertEqual(mine["focus"], "")  # switched off on purpose
        self.assertEqual(mine["task"], "")  # unreadable: no shortcut rather than a wrong one
        self.assertEqual(mine["toggle"], "Ctrl+Alt+H")
        self.assertNotIn("other", mine)
        self.assertEqual(set(hotkeys.NAMES), set(hotkeys.DEFAULTS))

    def test_two_things_on_the_same_keys(self):
        self.assertEqual(hotkeys.clashes(hotkeys.DEFAULTS), set())
        self.assertEqual(hotkeys.clashes({"ask": "Ctrl+Alt+H", "toggle": "Ctrl+Alt+H", "task": "", "focus": ""}), {"ask", "toggle"})

    def test_spare_keys_when_another_program_holds_the_usual_ones(self):
        usual = dict(hotkeys.DEFAULTS)
        self.assertEqual(hotkeys.spare("ask", usual, lambda keys: True), "Ctrl+Alt+A")
        self.assertEqual(hotkeys.spare("ask", usual, lambda keys: keys != "Ctrl+Alt+A"), "Ctrl+Alt+Shift+Space")  # that one is taken too
        self.assertEqual(hotkeys.spare("ask", {**usual, "task": "Ctrl+Alt+A"}, lambda keys: True), "Ctrl+Alt+Shift+Space")  # ours already
        self.assertEqual(hotkeys.spare("ask", usual, lambda keys: False), "")
        self.assertEqual(hotkeys.spare("nothing", usual, lambda keys: True), "")
        every = [keys for spares in hotkeys.SPARES.values() for keys in spares]
        self.assertEqual(set(hotkeys.SPARES), set(hotkeys.DEFAULTS))
        self.assertEqual(len(every), len(set(every) - set(hotkeys.DEFAULTS.values())), "a spare is used twice, or is a usual key")
        for keys in every:
            self.assertEqual(hotkeys.tidy(keys), keys)

    def test_one_cat_for_each_data_folder(self):
        from workcat.app import instance_name
        from workcat.store import default_folder

        self.assertEqual(instance_name(default_folder()), "WorkCat")
        self.assertEqual(instance_name(str(default_folder()).upper() + "\\"), "WorkCat")
        with tempfile.TemporaryDirectory() as folder:
            other = instance_name(Path(folder))
            self.assertRegex(other, r"^WorkCat-[0-9a-f]{12}$")
            self.assertEqual(other, instance_name(Path(folder) / "." ))
            self.assertNotEqual(other, instance_name(Path(folder) / "another"))


class ScreenEdgeTest(unittest.TestCase):
    def setUp(self):
        self.left = Monitor(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True)
        self.right = Monitor(Rect(1920, 0, 3840, 1080), Rect(1920, 0, 3840, 1040), False)

    def test_one_screen_has_two_edges_to_tuck_away_at(self):
        one = [self.left]
        self.assertEqual(world.outer_edge(10, 500, one, 40), ("left", self.left))
        self.assertEqual(world.outer_edge(1900, 500, one, 40), ("right", self.left))
        self.assertIsNone(world.outer_edge(960, 500, one, 40))
        self.assertIsNone(world.outer_edge(100, 500, one, 40))

    def test_the_edge_between_two_screens_is_not_one(self):
        both = [self.left, self.right]
        self.assertEqual(world.outer_edge(10, 500, both, 40), ("left", self.left))
        self.assertIsNone(world.outer_edge(1900, 500, both, 40))  # the other screen is beyond it
        self.assertIsNone(world.outer_edge(1930, 500, both, 40))
        self.assertEqual(world.outer_edge(3830, 500, both, 40), ("right", self.right))

    def test_a_screen_above_is_no_neighbour_to_the_side(self):
        above = Monitor(Rect(0, -1080, 1920, 0), Rect(0, -1080, 1920, -40), False)
        self.assertEqual(world.outer_edge(1900, 500, [self.left, above], 40), ("right", self.left))
        self.assertIsNone(world.outer_edge(500, 500, [], 40))


class SoundsTest(unittest.TestCase):
    @staticmethod
    def crossings(samples) -> int:
        """How often a wave passes through zero going up: for a clean voice, its pitch."""
        return sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)

    def test_every_sound_is_made_as_a_proper_wave_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, least, most in (("purr", 2.5, 4.0), ("greet", 1.5, 2.6), ("mew", 0.35, 0.7)):
                path = sounds.write(name, Path(folder) / "sounds" / f"{name}.wav")
                with wave.open(str(path), "rb") as made:
                    seconds = made.getnframes() / made.getframerate()
                    frames = made.readframes(made.getnframes())
                    self.assertEqual((made.getnchannels(), made.getsampwidth(), made.getframerate()), (1, 2, sounds.RATE))
                self.assertTrue(least <= seconds <= most, (name, seconds))
                heard = [int.from_bytes(frames[i:i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
                self.assertTrue(9000 < max(abs(x) for x in heard) < 22000, name)  # heard, but soft, and far from clipping
                self.assertTrue(abs(heard[0]) < 300 and abs(heard[-1]) < 300, (name, heard[0], heard[-1]))  # starts and ends in silence: no click
                self.assertTrue(abs(sum(heard) / len(heard)) < 40, name)  # rests on zero
                self.assertFalse(list(Path(folder, "sounds").glob("*.part")), "a half-written file was left behind")

    def test_the_sounds_are_the_same_every_time(self):
        self.assertEqual(sounds._purr(), sounds._purr())
        self.assertEqual(sounds._mew(), sounds._mew())

    def test_a_purr_is_a_run_of_thumps_and_breathes(self):
        purr = sounds._purr()
        rate = sounds.RATE
        # the strength over time, a hundredth of a second at a go
        step = rate // 100
        strength = [sum(abs(x) for x in purr[i:i + step]) / step for i in range(0, len(purr) - step, step)]
        peaks = sum(1 for a, b, c in zip(strength, strength[1:], strength[2:]) if b > a and b >= c and b > 0.25 * max(strength))
        per_second = peaks / (len(purr) / rate)
        self.assertTrue(15 <= per_second <= 30, per_second)  # a cat's purr: some 20 to 30 thumps a second
        turns = [i for i in range(40, len(strength) - 40) if strength[i] < 0.12 * max(strength)]
        self.assertTrue(turns, "the breath never turns round")

    def test_a_mew_goes_up_and_comes_down_again(self):
        mew = sounds._mew()
        rate = sounds.RATE
        part = len(mew) // 6
        pitch = [self.crossings(mew[i * part:(i + 1) * part]) * rate / part for i in range(6)]
        self.assertTrue(500 < min(pitch) and max(pitch) < 2000, pitch)  # a small animal's voice, not a whistle and not a growl
        loudness = [sum(abs(x) for x in mew[i * part:(i + 1) * part]) for i in range(6)]
        self.assertTrue(loudness[0] < max(loudness[1:4]) > loudness[5], loudness)  # soft, loud with the mouth open, soft

    def test_files_of_an_older_version_are_cleared_away(self):
        with tempfile.TemporaryDirectory() as folder:
            box = sounds.Sounds(Path(folder))
            box.folder.mkdir(parents=True)
            (box.folder / "purr.wav").write_bytes(b"old")
            (box.folder / "chime.wav").write_bytes(b"old")
            box._prepare()
            self.assertEqual(sorted(p.name for p in box.folder.iterdir()), sorted(f"{name}-{sounds.TAKE}.wav" for name in sounds.MAKERS))
            self.assertFalse(box.play("no such sound"))


class InterruptedSetupTest(unittest.TestCase):
    def test_what_lies_half_fetched_in_the_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = llm.Engine(Path(folder), port=11599)
            self.assertFalse(engine.unfinished())
            engine.home.mkdir(parents=True, exist_ok=True)
            (engine.home / "engine.zip.part").write_bytes(b"x")
            self.assertTrue(engine.unfinished())

    def test_only_a_setup_that_was_cut_short_goes_on_by_itself(self):
        import queue

        from workcat.ai import AI

        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))

            class App:
                pass

            app = App()
            app.store, app.settings, app.inbox = store, store.settings, queue.Queue()
            engine = llm.Engine(Path(folder) / "nowhere", port=11599)
            ai = AI(app, engine)
            self.assertEqual(ai.state, "missing")
            self.assertFalse(ai.interrupted())  # nothing was ever begun
            engine.home.mkdir(parents=True, exist_ok=True)
            (engine.home / "engine.zip.part").write_bytes(b"x")
            self.assertTrue(ai.interrupted())  # begun by a version that kept no note of it: the folder tells
            store.put(AI.WANTED, False)
            self.assertFalse(ai.interrupted())  # the person pressed Stop: it stays stopped
            store.put(AI.WANTED, True)
            self.assertTrue(ai.interrupted())
            ai.stop_setup()
            self.assertFalse(ai.interrupted())
            store.put(AI.WANTED, True)
            app.settings["ai_source"] = "online"  # the online AI answers meanwhile: the download still goes on
            self.assertTrue(ai.interrupted())
            app.settings["ai_model"] = "better"  # the big model was only looked at: it is never fetched unasked
            self.assertFalse(ai.interrupted())
            store.put(AI.WANTED, "better")  # ... but it is, once its own button was pressed
            self.assertTrue(ai.interrupted())
            app.settings["ai_model"] = "standard"
            self.assertFalse(ai.interrupted())  # what was asked for is not what is chosen now
            store.close()


class GoalsAndWeekTest(unittest.TestCase):
    def test_goals_live_with_the_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            first = store.add_task("Write the report", goal="2026-11-12")
            store.add_task("Call the bank", goal="2026-11-12")
            store.add_task("Water the plants")
            store.add_task("Yesterday's thing", goal="2026-11-11")
            self.assertEqual([goal["text"] for goal in store.goals("2026-11-12")], ["Write the report", "Call the bank"])
            store.update_task(first, done=1000)
            self.assertEqual([bool(goal["done"]) for goal in store.goals("2026-11-12")], [True, False])  # a goal done is still that day's goal
            self.assertEqual(len(store.tasks()), 3)
            store.update_task(first, goal=None)
            self.assertEqual(len(store.goals("2026-11-12")), 1)
            self.assertEqual(store.done_between(0, 1000), 0)
            self.assertEqual(store.done_between(1000, 1001), 1)
            store.close()

    def test_a_database_from_an_older_version_gets_the_new_column(self):
        with tempfile.TemporaryDirectory() as folder:
            old = sqlite3.connect(str(Path(folder) / "workcat.db"))
            old.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, text TEXT NOT NULL, created INTEGER NOT NULL, due INTEGER, place TEXT, repeat INTEGER NOT NULL DEFAULT 0, done INTEGER, shown INTEGER, tries INTEGER NOT NULL DEFAULT 0)")
            old.execute("INSERT INTO tasks (text, created) VALUES ('An old task', 1)")
            old.commit()
            old.close()
            store = Store(Path(folder))
            self.assertEqual([task["text"] for task in store.tasks()], ["An old task"])
            self.assertIsNone(store.tasks()[0]["goal"])
            store.add_task("A goal", goal="2026-11-12")
            self.assertEqual(len(store.goals("2026-11-12")), 1)
            store.close()

    def test_the_goal_comes_first_when_asked_what_to_do(self):
        tasks_ = ({"text": "Water the plants", "due": None, "place": None},)
        plain = advisor.ideas(advisor.Facts(now=1_000_000.0, tasks=tasks_))
        self.assertEqual(plain[0].key, "list")
        with_goal = advisor.ideas(advisor.Facts(now=1_000_000.0, tasks=tasks_, goals=({"text": "Write the report"},)))
        self.assertEqual(with_goal[0].key, "goal")
        self.assertIn("Write the report", with_goal[0].text)
        self.assertEqual([idea.key for idea in with_goal].count("list"), 0)  # one "open tasks" idea is enough

    def test_the_week_a_day_is_in(self):
        self.assertEqual(brain.week_of("2026-11-12"), ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"])
        self.assertEqual(brain.week_of("2026-11-09")[0], "2026-11-09")
        self.assertEqual(brain.week_of("2026-11-15")[0], "2026-11-09")  # Sunday ends the week
        self.assertEqual(brain.week_of("2027-01-01")[0], "2026-12-28")

    def test_hours_per_day(self):
        usage = {"2026-11-09": {"excel": {36: 900, 37: 600}, "chrome": {40: 300}}, "2026-11-11": {"excel": {36: 60}}}
        self.assertEqual(brain.per_day(usage, brain.week_of("2026-11-12")), [1800, 0, 60, 0, 0, 0, 0])

    def test_playing_lifts_the_mood(self):
        self.assertEqual(mood.condition(mood.Day(hour=15, since_play=60)).mood, "playful")
        self.assertNotEqual(mood.condition(mood.Day(hour=15, since_play=900)).mood, "playful")
        self.assertEqual(mood.condition(mood.Day(hour=15, since_play=60, focusing=True)).mood, "focused")  # work comes first


class BigModelTest(unittest.TestCase):
    """A big online model writes Cyrillic Uzbek well by itself: it gets the message as it was typed."""

    def test_no_detour_through_latin_letters(self):
        turn = assistant.Talk().turn("Эртага соат 10 да ҳисобот юборишни эслат", pivot=False)
        self.assertEqual(turn.sent, "Эртага соат 10 да ҳисобот юборишни эслат")
        self.assertEqual(turn.note, "(Answer in Uzbek, written in Cyrillic letters like this message.)")
        self.assertEqual(turn.shown("Албатта, эслатаман!"), "Албатта, эслатаман!")
        self.assertEqual(turn.shown("Albatta, ertaga eslataman!"), "Албатта, эртага эслатаман!")  # the safety net is still there
        self.assertEqual(turn.shown("Send the weekly report."), "Send the weekly report.")

    def test_the_instructions_follow(self):
        small = assistant.system_prompt("Miso", "Proud", "why", 25, "", pivot=True)[0]
        big = assistant.system_prompt("Miso", "Proud", "why", 25, "", pivot=False)[0]
        self.assertIn("write it in Latin letters", small)
        self.assertNotIn("write it in Latin letters", big)
        self.assertIn("answer in the alphabet the user wrote in", big)


class Pretend(BaseHTTPRequestHandler):
    """A stand-in for an online AI service. It speaks both forms."""
    seen: list = []
    answer_with: list = []  # HTTP statuses to answer with first, one per request
    message = "nope"
    no_json_mode = False
    models: list = ["b-model", "models/a-model"]  # what the service says it has

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Pretend.seen.append(("GET", self.path, {k.lower(): v for k, v in self.headers.items()}, None))
        if Pretend.answer_with:
            self._send(Pretend.answer_with.pop(0), json.dumps({"type": "error", "error": {"type": "some_error", "message": Pretend.message}}).encode())
        elif self.path == "/models":
            self._send(200, json.dumps({"data": [{"id": name} for name in Pretend.models]}).encode())
        else:
            self._send(404, b"{}")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        Pretend.seen.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if Pretend.answer_with:
            self._send(Pretend.answer_with.pop(0), json.dumps({"type": "error", "error": {"type": "some_error", "message": Pretend.message}}).encode())
            return
        asks_json = "response_format" in body or "output_config" in body
        if Pretend.no_json_mode and asks_json:
            self._send(400, json.dumps({"error": {"message": "unknown field response_format / output_config"}}).encode())
            return
        pieces = ['{"reply": "Hel', 'lo there"}']
        if self.path == "/v1/messages":
            events = [{"type": "message_start", "message": {}}, {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}}]
            events.append({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}})
            events += [{"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": piece}} for piece in pieces]
            events += [{"type": "message_delta", "delta": {"stop_reason": "end_turn"}}, {"type": "message_stop"}]
            text = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        else:
            chunks = [{"choices": [{"delta": {"role": "assistant"}}]}] + [{"choices": [{"delta": {"content": piece}}]} for piece in pieces] + [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]
            text = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        self._send(200, text.encode(), "text/event-stream")


class OnlineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pretend)
        cls.address = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.sleep, cloud.time.sleep = cloud.time.sleep, lambda seconds: None  # no waiting between tries here

    @classmethod
    def tearDownClass(cls):
        cloud.time.sleep = cls.sleep
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Pretend.seen, Pretend.answer_with, Pretend.message, Pretend.no_json_mode = [], [], "nope", False
        Pretend.models = ["b-model", "models/a-model"]
        self.claude = cloud.Online("claude", "sk-test", "", self.address)
        self.other = cloud.Online("other", "sk-test", "some-model", self.address)
        self.talk = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "hello"}]

    def test_claude_is_asked_the_way_its_api_wants(self):
        pieces = []
        answer = self.claude.chat("", self.talk, schema=assistant.SCHEMA, on_text=pieces.append)
        self.assertEqual(answer, '{"reply": "Hello there"}')
        self.assertEqual(pieces, ['{"reply": "Hel', 'lo there"}'])  # the thinking is not part of the answer
        method, path, headers, body = Pretend.seen[-1]
        self.assertEqual((method, path), ("POST", "/v1/messages"))
        self.assertEqual((headers["x-api-key"], headers["anthropic-version"]), ("sk-test", "2026-10-21"))
        self.assertNotIn("authorization", headers)
        self.assertEqual(body["model"], "claude-opus-5-5")  # the usual one when none is chosen
        self.assertEqual(body["system"], [{"type": "text", "text": "SYSTEM"}])
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])  # the system text travels apart
        self.assertTrue(body["stream"] and body["max_tokens"] >= 1000)
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual(body["output_config"]["format"], {"type": "json_schema", "schema": cloud.strict(assistant.SCHEMA)})
        for unwanted in ("temperature", "top_p", "thinking"):  # the newest models refuse these
            self.assertNotIn(unwanted, body)

    def test_the_lasting_part_of_the_instructions_is_marked_for_claudes_cache(self):
        talk = [{"role": "system", "content": "LASTING"}, {"role": "system", "content": "NOW"}, {"role": "user", "content": "hello"}]
        self.claude.chat("", talk, schema=assistant.SCHEMA)
        body = Pretend.seen[-1][3]
        self.assertEqual(body["system"], [{"type": "text", "text": "LASTING", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "NOW"}])
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
        self.other.chat("", talk)  # an OpenAI-style service gets one message, lasting part first
        self.assertEqual(Pretend.seen[-1][3]["messages"], [{"role": "system", "content": "LASTING\n\nNOW"}, {"role": "user", "content": "hello"}])

    def test_an_openai_style_service(self):
        pieces = []
        answer = self.other.chat("", self.talk, schema=assistant.SCHEMA, on_text=pieces.append)
        self.assertEqual(answer, '{"reply": "Hello there"}')
        self.assertEqual("".join(pieces), answer)
        method, path, headers, body = Pretend.seen[-1]
        self.assertEqual((method, path, headers["authorization"]), ("POST", "/chat/completions", "Bearer sk-test"))
        self.assertEqual(body, {"model": "some-model", "messages": self.talk, "stream": True, "response_format": {"type": "json_object"}})

    def test_a_service_that_cannot_be_held_to_json_is_asked_plainly(self):
        Pretend.no_json_mode = True
        for service in (self.other, self.claude):
            Pretend.seen = []
            self.assertEqual(service.chat("", self.talk, schema=assistant.SCHEMA), '{"reply": "Hello there"}')
            self.assertEqual(len(Pretend.seen), 2)
            self.assertNotIn("response_format", Pretend.seen[-1][3])
            self.assertNotIn("output_config", Pretend.seen[-1][3])

    def test_what_goes_wrong_is_said_in_plain_words(self):
        for status, message, expected in (
            (401, "invalid x-api-key", "The service did not accept the key. Is it a key for this service, and typed in full?"),
            (403, "forbidden", "The service did not accept the key. Is it a key for this service, and typed in full?"),
            (402, "pay", "The service says this account has no credit left."),
            (429, "You exceeded your current quota", "The service says this account has no credit left."),
            (400, "Your credit balance is too low to access the API", "The service says this account has no credit left."),
            (404, "model: nothing-9", "The service does not know this model, or its address is wrong. Please check both in the AI brain tab."),
            (400, "messages: roles must alternate", "The service refused the question: messages: roles must alternate"),
        ):
            for service in (self.claude, self.other):
                Pretend.answer_with, Pretend.message = [status], message
                with self.assertRaises(llm.EngineError) as caught:
                    service.chat("", self.talk)  # no shape asked for, so nothing to try without
                self.assertEqual(caught.exception.text(), expected, (status, service.service.name))
                self.assertNotIn("sk-test", str(caught.exception))

    def test_a_busy_service_is_asked_once_more(self):
        again = []
        for service in (self.claude, self.other):
            Pretend.answer_with = [429]
            self.assertEqual(service.chat("", self.talk, on_again=lambda: again.append(1)), '{"reply": "Hello there"}')
        self.assertEqual(len(again), 2)
        Pretend.answer_with = [529, 500]
        with self.assertRaises(llm.EngineError) as caught:
            self.claude.chat("", self.talk)
        self.assertEqual(caught.exception.text(), "The service is busy right now. Please try again in a moment.")
        self.assertEqual(Pretend.answer_with, [])  # twice, not for ever

    def test_no_connection(self):
        nowhere = cloud.Online("other", "sk-test", "m", "http://127.0.0.1:1")
        with self.assertRaises(llm.EngineError) as caught:
            nowhere.chat("", self.talk)
        self.assertEqual(caught.exception.text(), "No connection to the online service. Is the internet working, and is the address right?")

    def test_the_models_to_choose_from(self):
        self.assertEqual(self.other.models(), ["a-model", "b-model"])  # asked from the service, tidied and sorted
        self.assertEqual(Pretend.seen[-1][:2], ("GET", "/models"))
        Pretend.seen = []
        self.assertEqual(self.claude.models(), ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
        self.assertEqual(Pretend.seen, [])  # Claude's are known: nothing is asked

    def test_when_it_can_be_asked(self):
        self.assertTrue(self.claude.ready())
        self.assertFalse(cloud.Online("claude", "", "", "").ready())  # no key
        self.assertFalse(cloud.Online("openai", "sk-test", "", "").ready())  # no model chosen yet
        self.assertFalse(cloud.Online("other", "sk-test", "m", "").ready())  # no address
        self.assertEqual(cloud.Online("openai", "k", "m").address, "https://api.openai.com/v1")
        self.assertEqual(cloud.Online("nothing-like-it", "k", "m", "http://x/").address, "http://x")
        self.assertFalse(self.claude.local)

    def test_the_shape_is_spelled_out(self):
        made = cloud.strict(assistant.SCHEMA)
        self.assertIs(made["additionalProperties"], False)
        self.assertIs(made["properties"]["reminders"]["items"]["additionalProperties"], False)
        self.assertNotIn("additionalProperties", assistant.SCHEMA)  # the original is left as it was


class KeyTest(unittest.TestCase):
    def test_the_key_is_stored_locked(self):
        locked = cloud.lock("sk-ant-secret-123")
        self.assertNotIn("secret", locked)
        self.assertNotEqual(locked, cloud.lock("sk-ant-secret-124"))
        self.assertEqual(cloud.unlock(locked), "sk-ant-secret-123")
        self.assertEqual(cloud.unlock(cloud.lock("калит ключ")), "калит ключ")
        self.assertEqual((cloud.lock(""), cloud.unlock("")), ("", ""))
        self.assertEqual(cloud.unlock("not a locked key"), "")
        self.assertEqual(cloud.unlock(locked[:-8] + "AAAAAAA="), "")  # damaged: no key, never an error


if __name__ == "__main__":
    unittest.main()
