"""The offline AI engine: a language model that runs on this computer and nowhere else.

The engine is Ollama (open source, MIT licence). MyCat fetches it once from Ollama's
official release on github.com, checks it against a known fingerprint, and keeps it in its
own folder. It is not installed into Windows: MyCat starts it when you chat and Windows
ends it together with MyCat. The model's files come from Ollama's model library.

After that one-time setup nothing here uses the internet. The engine listens on
127.0.0.1 only, which other computers cannot reach.

    <data>/ai/engine/   the program (ollama.exe and its libraries)
    <data>/ai/models/   the model
    <app>/ai/           the same two folders shipped with the app, if someone packed them:
                        then nothing is downloaded at all
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .i18n import N_, T

log = logging.getLogger("workcat")

GIB = 1 << 30


@dataclass(frozen=True)
class Source:
    """One exact file on the internet: where it is, how big, and its SHA-256 fingerprint."""
    url: str
    size: int
    sha256: str


ENGINE_VERSION = "v0.40.16"
ENGINE = Source(
    f"https://github.com/ollama/ollama/releases/download/{ENGINE_VERSION}/ollama-windows-amd64.zip",
    1_618_244_995,
    "50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e",
)
ENGINE_UNPACKED = 5 * GIB  # room it needs once unpacked; generous on purpose


@dataclass(frozen=True)
class Model:
    name: str  # as the model library calls it
    size: int  # bytes to download
    needs_ram: int  # GB of memory for it to be pleasant
    context: int = 4096  # how much text it keeps in view at once, in tokens


MODELS = {
    "better": Model("gemma3:12b", 8_200_000_000, 16, 8192),
    "standard": Model("gemma3:4b", 3_350_000_000, 8, 8192),
    "small": Model("gemma3:1b", 810_000_000, 4),
}
BY_NAME = {model.name: model for model in MODELS.values()}
KEEP_LOADED = "30m"  # how long a model stays in memory after an answer
PORT = 11535
SYSTEM_PORT = 11434  # where a copy of Ollama installed by the person themselves listens
CREATE_NO_WINDOW = 0x08000000


class EngineError(Exception):
    """Something the person should be told in plain words.

    It is raised with the English sentence and the values that go into it, so that
    `text()` can give it in the person's own language where it is shown."""

    def __init__(self, message: str, **values):
        self.message, self.values = message, values
        super().__init__(message.format(**values) if values else message)

    def text(self) -> str:
        return T(self.message, **self.values)


class AnswerFailed(EngineError):
    """The engine gave up on one answer, as it does when a small model gets stuck
    repeating a token. Asking the same thing again nearly always works. `detail` is the
    engine's own wording, for the log."""

    def __init__(self, detail: str):
        super().__init__(N_("My words got tangled up. Please ask me once more."))
        self.detail = detail


class Cancelled(Exception):
    pass


def gb(size: float) -> str:
    """A size the way Windows shows it."""
    if size >= GIB / 10:
        return T("{n} GB", n=f"{size / GIB:.1f}")
    return T("{n} MB", n=f"{size / (1 << 20):.0f}")


def suggested_model(ram_bytes: int) -> str:
    return "standard" if ram_bytes >= 7 * GIB else "small"


def one_system(messages: list) -> list:
    """The same conversation with the instructions at its start joined into one message.

    The app hands them over in two parts: the lasting one (who the cat is, the rules) and
    the one that changes with every question (the time, the day so far). A service that
    can remember the lasting part between questions is given them apart; everyone else
    gets one message, lasting part first, which is also what lets the engine on this
    computer reuse its work on that part from one question to the next."""
    lead = []
    for message in messages:
        if message.get("role") != "system":
            break
        lead.append(message["content"])
    if len(lead) < 2:
        return messages
    return [{"role": "system", "content": "\n\n".join(lead)}] + messages[len(lead):]


def _local() -> urllib.request.OpenerDirector:
    """Talk to this computer directly, whatever proxy the system is set to use."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


PIECE = 8 << 20  # the file is fetched in pieces of this size
CONNECTIONS = 6  # this many pieces at a time
STALL = 25  # seconds without a byte before a connection is dropped and its piece asked for again


def download(source: Source, dest: Path, progress, cancel: threading.Event, connections: int = CONNECTIONS, piece: int = PIECE) -> None:
    """Fetch a file and refuse it unless its fingerprint matches.

    It comes in pieces over several connections at once: one slow or dropped connection
    then costs one piece, not the whole download. Finished pieces are remembered, so after
    an interruption only the missing ones are fetched.
    """
    part = dest.with_name(dest.name + ".part")
    note = dest.with_name(dest.name + ".pieces")
    count = max(1, (source.size + piece - 1) // piece)
    done: set = set()
    if part.exists():
        size = part.stat().st_size
        if size == source.size and note.exists():
            try:
                done = {int(i) for i in json.loads(note.read_text()) if 0 <= int(i) < count}
            except (OSError, ValueError, TypeError):
                done = set()
        elif size < source.size and not note.exists():
            done = set(range(size // piece))  # an unfinished front-to-back download: keep its whole pieces
        elif size > source.size:
            part.unlink()
    with open(part, "ab"):
        pass
    with open(part, "r+b") as out:
        out.truncate(source.size)

    def length(i: int) -> int:
        return min(piece, source.size - i * piece)

    lock = threading.Lock()
    todo = [i for i in range(count) if i not in done]
    got = [sum(length(i) for i in done)]
    failures: list = []

    def fetch() -> None:
        with open(part, "r+b") as out:
            while not cancel.is_set() and not failures:
                with lock:
                    if not todo:
                        return
                    i = todo.pop(0)
                first, size = i * piece, length(i)
                problem = None
                for attempt in range(6):
                    written = 0
                    try:
                        request = urllib.request.Request(source.url, headers={"User-Agent": "MyCat", "Range": f"bytes={first}-{first + size - 1}"})
                        with urllib.request.urlopen(request, timeout=STALL) as response:
                            if response.status != 206 and count > 1:
                                raise OSError("the server sent the whole file instead of a piece")
                            out.seek(first)
                            while written < size:
                                if cancel.is_set():
                                    return
                                data = response.read(min(1 << 16, size - written))
                                if not data:
                                    raise OSError("the connection closed early")
                                out.write(data)
                                written += len(data)
                                with lock:
                                    got[0] += len(data)
                        out.flush()
                        with lock:
                            done.add(i)
                        problem = None
                        break
                    except (OSError, ValueError) as error:
                        problem = error
                        with lock:
                            got[0] -= written
                        if cancel.wait(min(2**attempt, 15)):
                            return
                if problem is not None:
                    with lock:
                        failures.append(problem)
                    return

    workers = [threading.Thread(target=fetch, daemon=True) for _ in range(max(1, min(connections, len(todo))))]
    for worker in workers:
        worker.start()
    saved = time.monotonic()
    while any(worker.is_alive() for worker in workers):
        time.sleep(0.2)
        with lock:
            have, pieces = got[0], sorted(done)
        progress(have, source.size)
        if time.monotonic() - saved > 3:
            saved = time.monotonic()
            note.write_text(json.dumps(pieces))
    note.write_text(json.dumps(sorted(done)))
    if cancel.is_set():
        raise Cancelled()
    if len(done) < count:
        log.info("download interrupted: %s", failures[0] if failures else "unknown reason")
        raise EngineError(N_("The download was interrupted. Start the setup again and it will continue from there."))
    progress(source.size, source.size)
    digest = hashlib.sha256()
    with open(part, "rb") as data:
        for chunk in iter(lambda: data.read(1 << 22), b""):
            if cancel.is_set():
                raise Cancelled()
            digest.update(chunk)
    if digest.hexdigest() != source.sha256:
        part.unlink()
        note.unlink(missing_ok=True)
        raise EngineError(N_("The downloaded file is not the one expected, so it was deleted. Please try again."))
    os.replace(part, dest)
    note.unlink(missing_ok=True)


def unpack(archive: Path, dest: Path, progress, cancel: threading.Event) -> None:
    """Unzip into `dest`, replacing what was there only once everything is out."""
    fresh = dest.with_name(dest.name + ".new")
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir(parents=True)
    root = fresh.resolve()
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        total = sum(m.file_size for m in members) or 1
        done = 0
        for member in members:
            if cancel.is_set():
                raise Cancelled()
            target = (fresh / member.filename).resolve()
            if target != root and root not in target.parents:
                raise EngineError(N_("The downloaded archive is not safe to unpack."))
            bundle.extract(member, fresh)
            done += member.file_size
            progress(done, total)
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(fresh, dest)


def find_exe(folder: Path):
    """ollama.exe inside an unpacked engine folder, wherever the archive put it."""
    direct = folder / "ollama.exe"
    if direct.is_file():
        return direct
    return next((p for p in folder.rglob("ollama.exe") if p.is_file()), None) if folder.is_dir() else None


class Engine:
    """The engine on this computer: set it up, start it, talk to it.

    All methods that take time are meant to run on a worker thread."""

    def __init__(self, data_folder: Path, app_folder=None, port: int = PORT, engine: Source = ENGINE):
        self.home = Path(data_folder) / "ai"
        packed = Path(app_folder) / "ai" if app_folder else None
        if packed is not None and find_exe(packed / "engine"):
            self.home = packed  # shipped with the app
        self.source = engine
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.process = None
        self.lock = threading.Lock()
        self.keep_loaded = KEEP_LOADED  # -1: for as long as the engine runs
        self._nobody_until = 0.0  # see alive()

    # ------------------------------------------------------------------ what is there

    @property
    def exe(self):
        return find_exe(self.home / "engine")

    @property
    def models_folder(self) -> Path:
        return self.home / "models"

    def installed(self) -> bool:
        return self.exe is not None

    def alive(self, base: str = "", fresh: bool = False) -> bool:
        """Does an engine answer (at `base`, or where ours would be)?

        This is asked from the window's own thread whenever Chat or Settings is looked at,
        and most of the time no engine is running. Windows takes over a second to tell an
        ordinary request "nobody there", so the door is knocked on first, briefly, and a
        "nobody there" is believed for a moment (`fresh` asks again regardless)."""
        ours = not base
        base = base or self.base
        now = time.monotonic()
        if ours and not fresh and now < self._nobody_until:
            return False
        try:
            port = int(base.rsplit(":", 1)[1])
            socket.create_connection(("127.0.0.1", port), timeout=0.25).close()
            with _local().open(base + "/api/version", timeout=1.5) as response:
                return response.status == 200
        except (OSError, ValueError):
            if ours:
                self._nobody_until = now + 1.0
            return False

    def models(self) -> list:
        """Names of the models that are ready to use."""
        data = self._get("/api/tags")
        return [item.get("name") or item.get("model") or "" for item in data.get("models", [])]

    def has_model(self, name: str) -> bool:
        try:
            names = self.models()
        except EngineError:
            return False
        return name in names or (":" not in name and name + ":latest" in names)

    def ready(self, model: str) -> bool:
        """Everything is in place to chat with `model` (starts nothing)."""
        if self.alive():
            return self.has_model(model)
        if not self.installed():
            return False
        return self._model_on_disk(model)

    def _model_on_disk(self, name: str) -> bool:
        repo, _, tag = name.partition(":")
        return (self.models_folder / "manifests" / "registry.ollama.ai" / "library" / repo / (tag or "latest")).is_file()

    def unfinished(self) -> bool:
        """A setup was begun in this folder and did not reach its end: a half-fetched
        engine or a half-fetched model lies there. (Setting up again goes on from it.)"""
        if (self.home / "engine.zip.part").exists() or (self.home / "engine.zip").exists():
            return True
        blobs = self.models_folder / "blobs"
        return self.installed() and blobs.is_dir() and any(blobs.glob("*partial*"))

    # ------------------------------------------------------------------ running it

    def start(self) -> None:
        """Make sure the engine answers. Starts our own copy, hidden, if nothing does."""
        with self.lock:
            if self.alive(fresh=True):
                return
            if self.process is None or self.process.poll() is not None:
                exe = self.exe
                if exe is None:
                    if self.alive(f"http://127.0.0.1:{SYSTEM_PORT}"):  # the person has Ollama of their own: use it
                        self.base = f"http://127.0.0.1:{SYSTEM_PORT}"
                        return
                    raise EngineError(N_("The offline AI is not set up yet."))
                self.models_folder.mkdir(parents=True, exist_ok=True)
                env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{self.port}", OLLAMA_MODELS=str(self.models_folder))
                with open(self.home / "engine.log", "wb") as out:
                    self.process = subprocess.Popen(
                        [str(exe), "serve"], env=env, cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=out, stderr=out, creationflags=CREATE_NO_WINDOW
                    )
                try:
                    from . import win32

                    win32.end_with_us(int(self.process._handle))
                except Exception:  # not fatal: stop() still ends it on a normal quit
                    log.info("could not tie the engine to this process")
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if self.alive(fresh=True):
                    return
                if self.process.poll() is not None:
                    raise EngineError(N_("The offline AI could not start. Details are in engine.log in the data folder."))
                time.sleep(0.25)
            raise EngineError(N_("The offline AI took too long to start."))

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()

    # ------------------------------------------------------------------ one-time setup

    def room_needed(self, model: Model) -> int:
        need = 0 if self.installed() else self.source.size + ENGINE_UNPACKED
        return need + (0 if self._model_on_disk(model.name) else model.size) + GIB

    def setup(self, model: Model, report, cancel: threading.Event) -> None:
        """Download what is missing and get the model ready.
        report(stage, done, total) with stage 'engine', 'check', 'unpack', 'start', 'model' or 'ready'."""
        self.home.mkdir(parents=True, exist_ok=True)
        own_ollama = not self.installed() and self.alive(f"http://127.0.0.1:{SYSTEM_PORT}")
        if not self.installed() and not own_ollama:
            free = shutil.disk_usage(self.home).free
            need = self.room_needed(model)
            if free < need:
                raise EngineError(N_("Not enough free disk space: {need} needed, {free} free."), need=gb(need), free=gb(free))
            archive = self.home / "engine.zip"
            if not archive.exists():
                download(self.source, archive, lambda done, total: report("engine", done, total), cancel)
            report("unpack", 0, 1)
            unpack(archive, self.home / "engine", lambda done, total: report("unpack", done, total), cancel)
            archive.unlink(missing_ok=True)
            if self.exe is None:
                raise EngineError(N_("The downloaded engine is missing its program file."))
        report("start", 0, 1)
        self.start()
        if not self.has_model(model.name):
            self.pull(model.name, lambda done, total: report("model", done, total), cancel)
        report("ready", 1, 1)

    def pull(self, name: str, progress, cancel: threading.Event) -> None:
        layers: dict = {}
        for item in self._stream("/api/pull", {"model": name, "stream": True}, cancel, timeout=120):
            if item.get("error"):
                raise EngineError(N_("The model could not be downloaded: {detail}"), detail=str(item["error"]))
            if item.get("digest") and item.get("total"):
                layers[item["digest"]] = (item.get("completed", 0), item["total"])
                progress(sum(done for done, _ in layers.values()), sum(total for _, total in layers.values()))
            if item.get("status") == "success":
                return
        raise EngineError(N_("The model download ended early. Start the setup again and it will continue."))

    def remove(self) -> None:
        """Delete the engine and its models from this computer."""
        self.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    # ------------------------------------------------------------------ talking

    def _room(self, model: str) -> int:
        """The context a model is loaded with. Asking with another number makes the engine
        load the model afresh, so every request names the same one."""
        known = BY_NAME.get(model)
        return known.context if known else 4096

    def warm(self, model: str) -> None:
        """Load a model into memory before the first question, so that question does not
        wait for it. (A request without words does exactly that, and nothing else.)"""
        self.start()
        payload = {"model": model, "keep_alive": self.keep_loaded, "options": {"num_ctx": self._room(model)}}
        for _ in self._stream("/api/generate", payload, threading.Event(), timeout=300):
            pass

    def chat(self, model: str, messages: list, schema=None, on_text=None, cancel=None, options=None, on_again=None, tries: int = 2) -> str:
        """Send a conversation, return the whole answer. on_text gets it piece by piece.
        With `schema` the answer is JSON of exactly that shape.

        A small model now and then gets stuck repeating one token, and the engine gives
        up on that answer. It is then asked again (`tries` times in all), a little more
        freely; `on_again` is called first, so that pieces already received can be
        thrown away."""
        for attempt in range(1, tries + 1):
            try:
                return self._chat_once(model, messages, schema, on_text, cancel, {"temperature": 0.6 + 0.2 * (attempt - 1), **(options or {})})
            except AnswerFailed as error:
                log.info("the engine gave up on an answer (%s), try %d of %d", error.detail, attempt, tries)
                if attempt == tries:
                    raise
                if on_again:
                    on_again()
        return ""

    def _chat_once(self, model: str, messages: list, schema, on_text, cancel, options: dict) -> str:
        payload = {
            "model": model,
            "messages": one_system(messages),
            "stream": True,
            "keep_alive": self.keep_loaded,
            # num_predict: most answers are a few sentences; this only stops one that never ends
            "options": {"num_ctx": self._room(model), "num_predict": 700, **options},
        }
        if schema is not None:
            payload["format"] = schema
        pieces = []
        for item in self._stream("/api/chat", payload, cancel or threading.Event(), timeout=300):
            if item.get("error"):
                raise AnswerFailed(str(item["error"]))
            piece = (item.get("message") or {}).get("content") or ""
            if piece:
                pieces.append(piece)
                if on_text:
                    on_text(piece)
            if item.get("done"):
                break
        return "".join(pieces)

    # ------------------------------------------------------------------ plumbing

    def _get(self, path: str) -> dict:
        try:
            with _local().open(self.base + path, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            log.info("engine not answering: %s", error)
            raise EngineError(N_("The offline AI is not answering.")) from None

    def _stream(self, path: str, payload: dict, cancel: threading.Event, timeout: float):
        """POST and yield the answer's JSON lines as they arrive."""
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            response = _local().open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            with error:
                detail = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            raise EngineError("{detail}", detail=str(detail) or f"error {error.code}") from None
        except OSError as error:
            log.info("engine not answering: %s", error)
            raise EngineError(N_("The offline AI is not answering.")) from None
        try:
            for line in response:
                if cancel.is_set():
                    raise Cancelled()
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except OSError as error:
            log.info("engine connection broke: %s", error)
            raise EngineError(N_("The connection to the offline AI broke.")) from None
        finally:
            response.close()
