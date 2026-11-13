"""Tests for the offline AI engine, against a pretend engine on this computer.

Nothing here downloads the real engine or a real model.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workcat import llm  # noqa: E402


def make_zip() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("ollama.exe", b"not a real program" * 2000)
        bundle.writestr("lib/ollama/runner.dll", b"x" * 50_000)
    return data.getvalue()


ZIP = make_zip()


class Pretend(BaseHTTPRequestHandler):
    """Answers like the engine does, and also hands out the engine's zip."""
    models: list = []
    seen: list = []
    drop_once = False  # hang up in the middle of the next piece of the zip
    delay = 0.0  # seconds to wait before sending each piece
    fail_chat = False
    lock = threading.Lock()

    def log_message(self, *args):
        pass

    def _json(self, value, code=200):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _lines(self, items):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for item in items:
            self.wfile.write(json.dumps(item).encode() + b"\n")
            self.wfile.flush()

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "test"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": name} for name in Pretend.models]})
        elif self.path == "/engine.zip":
            first, last = 0, len(ZIP) - 1
            ranged = self.headers.get("Range")
            if ranged:
                a, _, b = ranged.split("=")[1].partition("-")
                first, last = int(a), int(b) if b else len(ZIP) - 1
            body = ZIP[first:last + 1]
            time.sleep(Pretend.delay)
            with Pretend.lock:
                Pretend.seen.append(("zip", first, len(body)))
                drop, Pretend.drop_once = Pretend.drop_once, False
            self.send_response(206 if ranged else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if drop:  # promises the piece, sends half of it, hangs up
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                self.connection.close()
                return
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        Pretend.seen.append((self.path, payload))
        if self.path == "/api/pull":
            name = payload["model"]
            if name == "missing:1b":
                self._lines([{"status": "pulling manifest"}, {"error": "file does not exist"}])
                return
            Pretend.models.append(name)
            self._lines([
                {"status": "pulling manifest"},
                {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 0},
                {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 600},
                {"status": "pulling bbb", "digest": "sha256:bbb", "total": 200, "completed": 200},
                {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 1000},
                {"status": "verifying sha256 digest"},
                {"status": "success"},
            ])
        elif self.path == "/api/chat":
            if Pretend.fail_chat:
                self._json({"error": "model 'x' not found"}, 404)
                return
            if Pretend.stuck:  # as when a small model repeats one token until the engine stops it
                Pretend.stuck -= 1
                self._lines([{"message": {"role": "assistant", "content": '{"reply": "Hel'}, "done": False}, {"error": "prediction aborted, token repeat limit reached"}])
                return
            words = ['{"reply": "Hel', 'lo there', '", "actions": []}']
            self._lines([{"message": {"role": "assistant", "content": w}, "done": False} for w in words] + [{"message": {"content": ""}, "done": True}])
        elif self.path == "/api/generate":  # no words to answer: the model is only loaded into memory
            self._lines([{"model": payload["model"], "response": "", "done": True, "done_reason": "load"}])
        else:
            self._json({"error": "not found"}, 404)


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pretend)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Pretend.models, Pretend.seen, Pretend.drop_once, Pretend.fail_chat, Pretend.delay, Pretend.stuck = [], [], False, False, 0.0, 0
        self.folder = tempfile.TemporaryDirectory()
        self.data = Path(self.folder.name)
        self.source = llm.Source(f"http://127.0.0.1:{self.port}/engine.zip", len(ZIP), hashlib.sha256(ZIP).hexdigest())
        self.engine = llm.Engine(self.data, port=self.port, engine=self.source)
        self.go = threading.Event()

    def tearDown(self):
        self.folder.cleanup()

    def test_setup_downloads_unpacks_and_gets_the_model(self):
        stages = []
        model = llm.Model("tiny:1b", 1200, 1)
        self.assertFalse(self.engine.installed())
        self.assertFalse(self.engine.ready("tiny:1b"))
        self.engine.setup(model, lambda stage, done, total: stages.append((stage, done, total)), self.go)
        self.assertTrue(self.engine.installed())
        self.assertEqual(self.engine.exe.name, "ollama.exe")
        self.assertTrue((self.data / "ai" / "engine" / "lib" / "ollama" / "runner.dll").is_file())
        self.assertFalse((self.data / "ai" / "engine.zip").exists())  # the archive is not kept
        names = [stage for stage, _, _ in stages]
        self.assertEqual([n for i, n in enumerate(names) if i == 0 or names[i - 1] != n], ["engine", "unpack", "start", "model", "ready"])
        self.assertIn(("engine", len(ZIP), len(ZIP)), stages)
        self.assertIn(("model", 1200, 1200), stages)
        self.assertTrue(self.engine.ready("tiny:1b"))

    def test_setup_again_downloads_nothing(self):
        model = llm.Model("tiny:1b", 1200, 1)
        self.engine.setup(model, lambda *a: None, self.go)
        Pretend.seen.clear()
        self.engine.setup(model, lambda *a: None, self.go)
        self.assertEqual(Pretend.seen, [])

    def pieces_asked(self) -> list:
        return sorted(entry[1:] for entry in Pretend.seen if entry[0] == "zip")

    def test_the_file_comes_in_pieces_over_several_connections(self):
        llm.download(self.source, self.data / "engine.zip", lambda *a: None, self.go, connections=3, piece=10_000)
        self.assertEqual((self.data / "engine.zip").read_bytes(), ZIP)
        asked = self.pieces_asked()
        self.assertEqual(len(asked), -(-len(ZIP) // 10_000))
        self.assertEqual(sum(size for _, size in asked), len(ZIP))
        self.assertFalse((self.data / "engine.zip.part").exists())
        self.assertFalse((self.data / "engine.zip.pieces").exists())

    def test_a_dropped_connection_costs_one_piece_not_the_download(self):
        Pretend.drop_once = True
        llm.download(self.source, self.data / "engine.zip", lambda *a: None, self.go, connections=2, piece=10_000)
        self.assertEqual((self.data / "engine.zip").read_bytes(), ZIP)
        self.assertEqual(len(self.pieces_asked()), -(-len(ZIP) // 10_000) + 1)  # one piece was asked for twice

    def test_a_stopped_download_continues_with_the_missing_pieces(self):
        def stop_halfway(done, total):
            if done >= total // 4:
                self.go.set()

        Pretend.delay = 0.08  # slow enough for the stop to land in the middle
        with self.assertRaises(llm.Cancelled):
            llm.download(self.source, self.data / "engine.zip", stop_halfway, self.go, connections=1, piece=5_000)
        first = len(self.pieces_asked())
        self.assertTrue((self.data / "engine.zip.pieces").exists())
        self.assertLess(first, -(-len(ZIP) // 5_000))
        self.go.clear()
        Pretend.seen.clear()
        Pretend.delay = 0.0
        llm.download(self.source, self.data / "engine.zip", lambda *a: None, self.go, connections=2, piece=5_000)
        self.assertEqual((self.data / "engine.zip").read_bytes(), ZIP)
        self.assertLess(len(self.pieces_asked()), -(-len(ZIP) // 5_000))  # only what was missing

    def test_an_older_unfinished_download_is_kept(self):
        (self.data / "engine.zip.part").write_bytes(ZIP[:25_000])  # written front to back, no list of pieces
        llm.download(self.source, self.data / "engine.zip", lambda *a: None, self.go, connections=2, piece=10_000)
        self.assertEqual((self.data / "engine.zip").read_bytes(), ZIP)
        self.assertEqual(min(start for start, _ in self.pieces_asked()), 20_000)  # the first two pieces were already there

    def test_a_wrong_file_is_refused_and_deleted(self):
        wrong = llm.Source(self.source.url, self.source.size, "0" * 64)
        with self.assertRaises(llm.EngineError):
            llm.download(wrong, self.data / "engine.zip", lambda *a: None, self.go)
        self.assertFalse((self.data / "engine.zip").exists())
        self.assertFalse((self.data / "engine.zip.part").exists())

    def test_cancel_stops_the_download(self):
        self.go.set()
        with self.assertRaises(llm.Cancelled):
            llm.download(self.source, self.data / "engine.zip", lambda *a: None, self.go)

    def test_unsafe_archive_is_refused(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as bundle:
            bundle.writestr("../outside.txt", b"x")
        archive = self.data / "bad.zip"
        archive.write_bytes(data.getvalue())
        try:
            llm.unpack(archive, self.data / "engine", lambda *a: None, self.go)
        except llm.EngineError:
            pass
        self.assertFalse((self.data / "outside.txt").exists())

    def test_pull_reports_errors_in_words(self):
        with self.assertRaises(llm.EngineError) as caught:
            self.engine.pull("missing:1b", lambda *a: None, self.go)
        self.assertIn("file does not exist", str(caught.exception))

    def test_chat_streams_and_asks_for_the_shape(self):
        pieces = []
        schema = {"type": "object"}
        answer = self.engine.chat("tiny:1b", [{"role": "user", "content": "hi"}], schema=schema, on_text=pieces.append)
        self.assertEqual(answer, '{"reply": "Hello there", "actions": []}')
        self.assertEqual(pieces, ['{"reply": "Hel', 'lo there', '", "actions": []}'])
        path, sent = Pretend.seen[-1]
        self.assertEqual((path, sent["model"], sent["format"], sent["stream"]), ("/api/chat", "tiny:1b", schema, True))
        self.assertEqual(sent["messages"], [{"role": "user", "content": "hi"}])

    def test_chat_error_is_readable(self):
        Pretend.fail_chat = True
        with self.assertRaises(llm.EngineError) as caught:
            self.engine.chat("x", [{"role": "user", "content": "hi"}])
        self.assertIn("not found", str(caught.exception))

    def test_an_answer_the_engine_gave_up_on_is_asked_for_again(self):
        Pretend.stuck = 1
        pieces, restarts = [], []

        def again():
            restarts.append(list(pieces))
            pieces.clear()

        answer = self.engine.chat("tiny:1b", [{"role": "user", "content": "hi"}], on_text=pieces.append, on_again=again)
        self.assertEqual(answer, '{"reply": "Hello there", "actions": []}')
        self.assertEqual(restarts, [['{"reply": "Hel']])  # the half answer was handed over, then thrown away
        self.assertEqual("".join(pieces), answer)
        chats = [sent for path, sent in Pretend.seen if path == "/api/chat"]
        self.assertEqual(len(chats), 2)
        self.assertGreater(chats[1]["options"]["temperature"], chats[0]["options"]["temperature"])  # a little more freely
        self.assertEqual(chats[0]["options"]["num_predict"], 700)

    def test_a_model_is_loaded_ahead_of_the_first_question(self):
        self.engine.warm("gemma3:4b")
        path, sent = Pretend.seen[-1]
        self.assertEqual(path, "/api/generate")
        self.assertEqual(sent, {"model": "gemma3:4b", "keep_alive": "30m", "options": {"num_ctx": 8192}})  # no words: nothing is asked
        self.engine.chat("gemma3:4b", [{"role": "user", "content": "hi"}])
        asked = Pretend.seen[-1][1]
        self.assertEqual(asked["options"]["num_ctx"], 8192)  # the same room it was loaded with: otherwise the engine loads it afresh
        self.assertEqual(asked["keep_alive"], "30m")
        self.engine.keep_loaded = -1  # "keep it ready all the time"
        self.engine.chat("gemma3:1b", [{"role": "user", "content": "hi"}])
        self.assertEqual((Pretend.seen[-1][1]["keep_alive"], Pretend.seen[-1][1]["options"]["num_ctx"]), (-1, 4096))

    def test_the_two_parts_of_the_instructions_reach_the_engine_as_one(self):
        talk = [{"role": "system", "content": "LASTING"}, {"role": "system", "content": "NOW"}, {"role": "user", "content": "hi"}]
        self.engine.chat("tiny:1b", talk)
        self.assertEqual(Pretend.seen[-1][1]["messages"], [{"role": "system", "content": "LASTING\n\nNOW"}, {"role": "user", "content": "hi"}])
        self.assertEqual(len(talk), 3)  # what was handed over is left as it was

    def test_stuck_again_and_again_is_said_in_plain_words(self):
        Pretend.stuck = 5
        with self.assertRaises(llm.AnswerFailed) as caught:
            self.engine.chat("tiny:1b", [{"role": "user", "content": "hi"}])
        self.assertEqual(caught.exception.text(), "My words got tangled up. Please ask me once more.")
        self.assertIn("token repeat limit", caught.exception.detail)  # the engine's own words go to the log
        self.assertEqual(len([1 for path, _ in Pretend.seen if path == "/api/chat"]), 2)  # twice, not for ever

    def test_nothing_running_and_nothing_installed(self):
        lonely = llm.Engine(self.data, port=1)  # nothing listens on port 1
        self.assertFalse(lonely.alive())
        self.assertFalse(lonely.ready("gemma3:4b"))
        with self.assertRaises(llm.EngineError):
            lonely.models()

    def test_a_packed_copy_next_to_the_app_is_used(self):
        app = self.data / "app"
        (app / "ai" / "engine").mkdir(parents=True)
        (app / "ai" / "engine" / "ollama.exe").write_bytes(b"x")
        engine = llm.Engine(self.data / "data", app_folder=app, port=1)
        self.assertEqual(engine.home, app / "ai")
        self.assertTrue(engine.installed())
        self.assertEqual(llm.Engine(self.data / "data", app_folder=self.data / "empty", port=1).home, self.data / "data" / "ai")

    def test_sizes_and_choice(self):
        self.assertEqual(llm.gb(1_618_244_995), "1.5 GB")
        self.assertEqual(llm.gb(50 * (1 << 20)), "50 MB")
        self.assertEqual(llm.suggested_model(32 * llm.GIB), "standard")
        self.assertEqual(llm.suggested_model(4 * llm.GIB), "small")
        self.assertGreater(self.engine.room_needed(llm.MODELS["standard"]), llm.MODELS["standard"].size)


if __name__ == "__main__":
    unittest.main()
