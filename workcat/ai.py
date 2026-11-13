"""The AI as the app sees it: is it there, set it up, ask it something.

There are two brains, and three ways to use them, chosen in the AI brain tab:

    offline  a model that runs on this computer (llm.py). The default: nothing leaves the PC.
    online   a service on the internet, with your own key (cloud.py). Only if switched on.
    both     the online one while it can be reached, the one on this computer when it
             cannot: the switch is made by itself, there and back.

Everything slow (downloading, starting the engine, waiting for an answer) happens on a
worker thread that only puts messages into the app's inbox. The app hands them to
`handle` on the window's own thread, which is the only place state changes.

`state` says whether the chosen brain can answer:

    missing  offline, and no model is on this computer yet
    setup    offline, and the first model is being downloaded and prepared
    nokey    online, but no key (or no model) has been given
    ready    can be asked

Fetching the offline AI is a thing of its own (`fetching`, with its progress): it goes on
while the online AI answers, and while a model that is already here answers.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import assistant, cloud, llm, reader
from .i18n import N_, T

log = logging.getLogger("workcat")

IDLE_STOP = 30 * 60  # the offline engine is shut down after this long without a question
SMALL_ROOM = 2500  # characters of a window's text that the Small model has room for
DOWN_FOR = 60  # seconds the online AI is left alone after it could not be reached; then it is tried again, by itself
WATCH_EVERY = 60  # in "both": how often the way to the online AI is looked at while nothing is asked
WARM_GAP = 45  # seconds: the model is not asked into memory more often than this
ROOM = {"short": 400, "normal": 700, "detailed": 1400}  # how long an answer of the offline model may get, in tokens
ORDER = ("better", "standard", "small")  # which other offline model stands in while the chosen one is not here


def app_folder() -> Path:
    """Where the app's own files are: an `ai` folder next to them is used as it is."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class Plan:
    """One way of getting a question answered: who is asked, and what they are sent."""
    brain: object
    model: str
    turn: assistant.Turn
    messages: list
    options: dict
    local: bool


class AI:
    def __init__(self, app, engine=None):
        self.app = app
        self.engine = engine or llm.Engine(app.store.folder, app_folder=app_folder())
        self.talk = assistant.Talk()
        if app.settings.get("ai_keep_talk"):
            self.talk.load(app.store.talk())  # the conversation from before the app was closed
        self._service = (None, None)  # the settings it was made from, and the cloud.Online
        self.fetching = False  # the offline AI is being downloaded and prepared
        self.fetched = None  # the llm.Model that is being fetched
        self.local = None  # the offline llm.Model that can answer right now, if any
        self.state = ""
        self.stage, self.done, self.total = "", 0, 1
        self.error = ""
        self.busy = False  # an answer is on its way
        self.asked = None  # the assistant.Turn being answered
        self.cancel = threading.Event()
        self.last_used = 0.0
        self.last_warm = 0.0
        self.last_find = 0.0
        self.warming = False
        self.down_until = 0.0  # (time.monotonic) until then the online AI is taken to be out of reach
        self.down_why = ""  # ... and this is what it said, or what was found
        self.last_watch = 0.0
        self.watching = False
        self.answered = None  # who gave the last answer: {"local": bool, "down": the online AI was out of reach}
        self.found: dict = {}  # online service -> the models it listed
        self.timing = None  # the last answer: (seconds to its first word, seconds in all, who gave it)
        self.listeners: list = []  # called with (what, payload) when something changes
        self.moved_to = self.right_service()  # the service a key saved under the wrong one was moved to, if any
        self.settle()

    # ------------------------------------------------------------------ which brain

    @property
    def online(self) -> bool:
        """The online service is the brain, or one of the two."""
        return self.app.settings.get("ai_source") in ("online", "both")

    @property
    def both(self) -> bool:
        """Online while it can be reached, this computer when it cannot."""
        return self.app.settings.get("ai_source") == "both"

    def online_down(self) -> bool:
        """The online AI could not be reached a moment ago, and is being left alone."""
        return time.monotonic() < self.down_until

    def service(self) -> cloud.Online:
        """The online service as the AI brain tab describes it."""
        s = self.app.settings
        made_from = (s.get("ai_service"), s.get("ai_key"), s.get("ai_online_model"), s.get("ai_address"))
        if self._service[0] != made_from:
            self._service = (made_from, cloud.Online(made_from[0] or "claude", cloud.unlock(made_from[1] or ""), made_from[2] or "", made_from[3] or ""))
            self.down_until = 0.0  # another service, key or address: what was out of reach before says nothing about this one
        return self._service[1]

    def right_service(self) -> str:
        """A key that was saved under a service it plainly does not belong to (a Claude key
        with OpenAI chosen, as an earlier version let happen) moves the choice to its own
        service. Returns that service's name if something was changed, else ""."""
        s = self.app.settings
        if s.get("ai_service") == "other" and s.get("ai_address"):
            return ""  # an address typed by hand is a choice made on purpose: it stays
        whose = cloud.guess_service(cloud.unlock(s.get("ai_key") or ""))
        if not whose or whose == s.get("ai_service"):
            return ""
        s["ai_service"], s["ai_online_model"], s["ai_address"] = whose, "", ""
        self.app.store.save_settings()
        return cloud.SERVICES[whose].name

    @property
    def brain(self):
        """Whoever answers the next question: the online service or the engine on this computer."""
        if not self.online:
            return self.engine
        if self.both and self.local is not None and (not self.service().ready() or self.online_down()):
            return self.engine
        return self.service()

    @property
    def model(self) -> llm.Model:
        """The offline model chosen in the AI brain tab."""
        return llm.MODELS.get(self.app.settings.get("ai_model"), llm.MODELS["standard"])

    def local_model(self):
        """The offline model that can answer now: the chosen one, or, while that one is
        not on this computer (yet), another one that is. None if there is none."""
        chosen = self.model
        if self.engine.ready(chosen.name):
            return chosen
        for key in ORDER:
            other = llm.MODELS[key]
            if other is not chosen and self.engine.ready(other.name):
                return other
        return None

    @property
    def model_name(self) -> str:
        """The name of the model that answers."""
        brain = self.brain
        return (self.local or self.model).name if brain is self.engine else brain.model

    def settle(self) -> None:
        """Work the state out again: after a change in the settings, a removal, a setup."""
        self.engine.keep_loaded = -1 if self.app.settings.get("ai_keep_ready") else llm.KEEP_LOADED
        self.local = self.local_model()
        if self.online and not self.both:
            self.state = "ready" if self.service().ready() else "nokey"
        elif self.local is not None or (self.both and self.service().ready()):
            self.state = "ready"  # in "both", either half is enough to answer
        else:
            self.state = "setup" if self.fetching else "missing"

    def download_size(self) -> int:
        """Bytes still to fetch for the chosen offline model."""
        engine = 0 if self.engine.installed() else self.engine.source.size
        return engine + (0 if self.engine.ready(self.model.name) else self.model.size)

    def _post(self, what: str, payload=None) -> None:
        self.app.inbox.put(("ai", (what, payload)))

    def _tell(self, what: str, payload=None) -> None:
        for listener in list(self.listeners):
            try:
                listener(what, payload)
            except Exception:
                log.exception("ai listener")

    # ------------------------------------------------------------------ setting up the offline brain

    WANTED = "ai_wanted"  # remembered: which offline model the person asked for ("standard", ...), or False once its setup was stopped

    def interrupted(self) -> bool:
        """The offline AI was being set up and that was cut short: the computer was
        switched off, the app was closed or updated. (Not: the person pressed Stop, and
        not: it failed and said why.) Then the setup may go on by itself, whichever
        brain is the one that answers.

        It goes on only with the model that was asked for. Choosing another one in the
        list downloads nothing until its button is pressed, least of all the big one."""
        chosen = self.app.settings.get("ai_model")
        if self.fetching or self.engine.ready(self.model.name):
            return False
        wanted = self.app.store.get(self.WANTED)
        if wanted is None:  # nothing remembered, as after a version that did not: go by what lies in the folder
            return chosen != "better" and self.engine.unfinished()
        if wanted is True:  # remembered by a version that knew two models
            return chosen != "better"
        return bool(wanted) and wanted == chosen

    def progress_words(self) -> str:
        """Where the one-time setup stands, in a sentence."""
        share = self.done / max(self.total, 1)
        amount = f"{llm.gb(self.done)} / {llm.gb(self.total)}"
        if self.stage == "engine":
            return T("Checking the download...") if share >= 1 else T("Downloading the engine: {p}%  ({amount})", p=int(share * 100), amount=amount)
        if self.stage == "unpack":
            return T("Unpacking: {p}%", p=int(share * 100))
        if self.stage == "model":
            return T("Downloading the model: {p}%  ({amount})", p=int(share * 100), amount=amount)
        return T("Starting...")

    def setup(self) -> None:
        """Fetch the chosen offline model (and the engine, if it is not here yet)."""
        if self.fetching:
            return
        chosen = self.app.settings.get("ai_model")
        self.app.store.put(self.WANTED, chosen if chosen in llm.MODELS else "standard")
        self.fetching, self.error = True, ""
        self.stage, self.done, self.total = "engine", 0, 1
        self.cancel = threading.Event()
        cancel, model = self.cancel, self.model
        self.fetched = model
        last = [0.0, ""]

        def report(stage: str, done: int, total: int) -> None:
            now = time.monotonic()
            if stage != last[1] or now - last[0] >= 0.25 or done >= total:
                last[0], last[1] = now, stage
                self._post("progress", (stage, done, total))

        def work() -> None:
            try:
                self.engine.setup(model, report, cancel)
                self._post("ready")
            except llm.Cancelled:
                self._post("stopped")
            except llm.EngineError as error:
                self._post("failed", error)
            except Exception as error:  # a full disk, a broken network: say so, do not crash
                log.exception("ai setup")
                self._post("failed", str(error) or type(error).__name__)

        threading.Thread(target=work, name="ai-setup", daemon=True).start()
        self.settle()
        self._tell("state")

    def stop_setup(self) -> None:
        """The person pressed Stop: what was fetched stays, and nothing goes on by itself."""
        self.app.store.put(self.WANTED, False)
        self.cancel.set()

    def remove(self) -> None:
        """Delete the engine and its models from this computer."""
        self.app.store.put(self.WANTED, False)
        self.cancel.set()
        self.engine.remove()
        self.settle()
        self._tell("state")

    # ------------------------------------------------------------------ two small errands: a test, and the list of models

    def _errand(self, what: str, job) -> None:
        def work() -> None:
            try:
                self._post(what, (True, job()))
            except llm.EngineError as error:
                self._post(what, (False, error))
            except Exception as error:
                log.exception("ai %s", what)
                self._post(what, (False, str(error) or type(error).__name__))

        threading.Thread(target=work, name="ai-" + what, daemon=True).start()

    def test(self, which: str = "") -> None:
        """Ask one tiny question, and time it: of the "online" AI, of the "offline" one,
        or (said nothing) of whoever answers. 'tested' arrives with
        (True, {"model": ..., "seconds": ...}) or (False, what is wrong). Online, no
        model needs to be chosen first: the service is asked which it has, and one is
        picked (and kept, if none was chosen)."""
        question = [{"role": "user", "content": "Reply with the single word: ok"}]
        if which == "online" or (not which and self.online and (not self.both or self.service().reachable())):
            service, key = self.service(), self.app.settings.get("ai_service") or "claude"

            def job():
                names, model = None, service.model
                if not model:
                    names = service.models()
                    model = cloud.pick_default(key, names)
                    if not model:
                        raise llm.EngineError(N_("The service listed no models to talk to."))
                started = time.monotonic()
                service.chat(model, question)
                return {"service": key, "model": model, "names": names, "seconds": time.monotonic() - started}
        else:
            engine, model = self.engine, (self.local or self.model).name
            self.last_used = time.time()

            def job():
                engine.start()
                started = time.monotonic()
                engine.chat(model, question, options={"num_predict": 8})
                return {"service": "", "model": model, "names": None, "seconds": time.monotonic() - started}

        self._errand("tested", job)

    def list_models(self) -> None:
        """Ask the online service which models it has: 'models' arrives with (True, names)
        or (False, what is wrong). If no model was chosen yet, one is picked."""
        service, key = self.service(), self.app.settings.get("ai_service") or "claude"
        self._errand("models", lambda: {"service": key, "model": "", "names": service.models(), "seconds": 0.0})

    def find_model(self) -> None:
        """The online AI is chosen and has its key, but no model: ask the service which it
        has, so that one is picked and the cat can answer. (After a key was moved to its
        own service, say. Asked at most twice a minute.)"""
        now = time.time()
        if not self.online or now - self.last_find < 30:
            return
        service = self.service()
        if service.reachable() and not service.model:
            self.last_find = now
            self.list_models()

    def _learned(self, result: dict) -> None:
        """What an errand found out about the online service: its models, and one to use."""
        key, names = result["service"], result["names"]
        if not key:
            return
        if names is not None:
            self.found[key] = list(names)
        settings = self.app.settings
        if settings.get("ai_service") != key or settings.get("ai_online_model"):
            return
        model = result["model"] or cloud.pick_default(key, names or ())
        if model:
            settings["ai_online_model"] = result["model"] = model
            self.app.store.save_settings()
            self.settle()
            self._tell("state")

    # ------------------------------------------------------------------ asking

    def warm(self) -> None:
        """Someone is about to ask (the ask box or Chat was opened): have the offline
        model in memory by the time they do, so the first answer does not wait for it."""
        now = time.time()
        if self.brain is not self.engine or self.local is None or self.busy or self.warming or now - self.last_warm < WARM_GAP:
            return
        self.warming, self.last_warm, self.last_used = True, now, now
        engine, model = self.engine, self.local.name

        def work() -> None:
            try:
                engine.warm(model)
            except Exception as error:  # the question itself will say what is wrong
                log.info("could not load the offline model ahead of time: %s", error)
            finally:
                self.warming = False

        threading.Thread(target=work, name="ai-warm", daemon=True).start()

    def _plan(self, brain, model: str, text: str, system, keep, tasks, notes, first: bool, material=None) -> Plan:
        local = getattr(brain, "local", True)
        # a small model on this computer is helped with Uzbek's two alphabets, and what it
        # wants done is checked against the person's words; a big online one needs neither
        turn = self.talk.turn(text, self.app.settings.get("language", "en"), keep, pivot=local, careful=local, remember=first)
        turn.tasks, turn.notes = dict(tasks or {}), dict(notes or {})
        if material:
            # as much of the window's text as this model has room for beside its instructions
            known = llm.BY_NAME.get(model) if local else None
            room = SMALL_ROOM if known is not None and known.context <= 4096 else reader.MOST
            turn.material = (material[0], material[1][:room])
        said = system(local) if callable(system) else system
        options = {"num_predict": ROOM.get(self.app.settings.get("ai_length"), ROOM["normal"])} if local else {}
        return Plan(brain, model, turn, self.talk.messages(said, turn), options, local)

    def look_and_ask(self, hwnd: int, text: str, system, keep=(), tasks=None, notes=None, online_ok: bool = False) -> bool:
        """Read what a window shows, then put the question to the model with it. 'reading'
        is told at once (with the program's name); if nothing could be read, 'error'.

        `online_ok`: whether the person allowed such text to go to the online AI. If not,
        only the AI on this computer is asked, whichever is chosen otherwise."""
        if self.busy or (self.state != "ready" if online_ok else self.local is None):
            return False  # (asked before the window is read: nothing is read that nobody may be shown)
        self.busy = True
        self.last_used = time.time()
        _program, name = reader.identity(hwnd)

        def work() -> None:
            self._post("read", (reader.read(hwnd), text, system, keep, tasks, notes, online_ok))

        threading.Thread(target=work, name="ai-read", daemon=True).start()
        self._tell("reading", name)
        return True

    def ask(self, text: str, system, keep=(), tasks=None, notes=None, material=None, local_only: bool = False) -> bool:
        """Send a line to the model. 'asked' is told at once; while the model writes,
        'text' arrives again and again with the reply so far; then 'answer' with the
        whole of it.

        `material`: (a program's name, what its window shows), to go along with this one
        question. `local_only`: ask only the AI on this computer (that text may not go
        online).

        `system`: the instructions, or a function giving them for a brain on this
        computer (True) or an online one (False). `keep` are names that stay in Latin
        letters when an Uzbek answer is put into Cyrillic. `tasks` and `notes` (number ->
        text) are the lists the model is shown: it may only point at those.

        With "both" chosen, the online AI is asked first, after a quick look whether it
        can be reached at all. If it cannot, or does not answer, the one on this computer
        answers instead ('switched' is told first), and the online one is left alone for
        a minute before it is tried again."""
        if self.busy or (self.state != "ready" and not (local_only and self.local is not None)):
            return False
        plans, skipped = [], ""
        if self.online and self.service().ready() and not local_only:
            if self.both and self.local is not None and self.online_down():
                skipped = self.down_why or "-"  # out of reach a moment ago: not asked this time
            else:
                plans.append(self._plan(self.service(), self.service().model, text, system, keep, tasks, notes, True, material))
        if (local_only or self.both or not self.online) and self.local is not None:
            plans.append(self._plan(self.engine, self.local.name, text, system, keep, tasks, notes, not plans, material))
        if not plans:
            return False
        self.busy = True
        self.last_used = time.time()
        look_first = self.both and len(plans) > 1  # is the online AI there at all? Two seconds tell
        self.asked = plans[0].turn
        answering = [plans[0], assistant.ReplyReader(), None]  # who is being asked, the reader of the reply, when its first word came
        began = time.monotonic()

        def piece(part: str) -> None:
            if answering[1].feed(part):
                if answering[2] is None:
                    answering[2] = time.monotonic() - began
                self._post("text", answering[0].turn.live(answering[1].text))

        def again() -> None:  # that answer was given up on and a new one starts
            answering[1] = assistant.ReplyReader()
            self._post("text", "")

        def work() -> None:
            problem = None
            for at, plan in enumerate(plans):
                answering[0], answering[1] = plan, assistant.ReplyReader()
                try:
                    if look_first and at == 0 and not plan.brain.knock():
                        raise llm.EngineError(N_("No connection to the online service. Is the internet working, and is the address right?"))
                    plan.brain.start()
                    raw = plan.brain.chat(plan.model, plan.messages, schema=assistant.SCHEMA, on_text=piece, on_again=again, options=plan.options)
                    self._post("answer", (plan, raw, problem, (answering[2], time.monotonic() - began), skipped))
                    return
                except Exception as error:
                    if not isinstance(error, llm.EngineError):
                        log.exception("ai ask")
                        error = str(error) or type(error).__name__
                    if at + 1 < len(plans):  # the other brain is asked instead
                        log.info("the online AI did not answer (%s): asking the one on this computer", error)
                        problem = error
                        self._post("switched", error)
                        continue
                    self._post("error", error)
                    return

        threading.Thread(target=work, name="ai-ask", daemon=True).start()
        self._tell("asked", text)
        self._tell("thinking")
        return True

    def clear_talk(self) -> None:
        """Forget the conversation, here and in what is kept for the next start."""
        self.talk.clear()
        self.app.store.clear_talk()

    # ------------------------------------------------------------------ on the window's thread

    def handle(self, what: str, payload) -> None:
        if isinstance(payload, llm.EngineError):
            payload = payload.text()  # put into the person's language here, on the window's thread
        if what == "progress":
            self.stage, self.done, self.total = payload
            self._tell("progress")
        elif what == "ready":
            self.fetching = False
            self.app.store.put(self.WANTED, False)  # done: there is nothing left to go on with
            self.settle()
            self._tell("state")
            self.app.on_ai_ready()
        elif what in ("failed", "stopped"):
            self.fetching = False
            self.settle()
            self.error = payload or ""
            self._tell("state")
            if what == "failed":
                self.app.store.put(self.WANTED, False)  # it said why: trying again is for the person to decide
                self.app.on_ai_failed(self.error)
        elif what == "text":
            self._tell("text", payload)
        elif what == "switched":
            self.down_until, self.down_why = time.monotonic() + DOWN_FOR, str(payload)  # left alone for a minute, then tried again
            self._tell("text", "")  # what the first brain had written so far is taken back
            self._tell("switched", payload)
        elif what == "net":  # the look at the way to the online AI, once a minute in "both"
            self.watching = False
            was = self.online_down()
            if payload:
                self.down_until = 0.0
            else:
                self.down_until, self.down_why = time.monotonic() + DOWN_FOR, T("No connection to the online service. Is the internet working, and is the address right?")
            if was != self.online_down():
                self._tell("state")
        elif what == "read":  # the window has been read (or not): now the question can be put
            seen, text, system, keep, tasks, notes, online_ok = payload
            self.busy = False
            if not seen.text:
                why = {
                    "gone": T("{name} is not open any more.", name=seen.name or "?"),
                    "hidden": T("{name} is not showing on the screen right now.", name=seen.name),
                    "late": T("{name} took too long to answer.", name=seen.name),
                }.get(seen.why, T("I could not read anything in {name}. Some programs do not let their window be read.", name=seen.name))
                self._tell("error", why)
            elif not self.ask(text, system, keep, tasks, notes, material=(seen.name, seen.text), local_only=not online_ok):
                self._tell("error", T("What I read in other programs may only go to my AI on this computer, and that one is not ready."))
        elif what == "answer":
            plan, raw, problem, (first, whole), skipped = payload
            self.busy = False
            if not plan.local:
                self.down_until = 0.0  # it answers
            self.answered = {"local": plan.local, "down": bool(skipped) or problem is not None}
            self.last_used = time.time()
            self.asked = turn = plan.turn
            self.timing = (first if first is not None else whole, whole, plan.model)
            log.info("answer from %s: first word after %.1f s, whole after %.1f s", plan.model, self.timing[0], whole)
            # in the alphabet the question came in, and without what is on the list already
            reply, actions = turn.result(raw, [task["text"] for task in self.app.store.tasks()])
            if not turn.material:
                # (An answer about what a window showed is not taken into the conversation,
                # here or on disk: what was read is for that one answer.)
                self.talk.add(turn, raw)
                if self.app.settings.get("ai_keep_talk"):
                    self.app.store.add_talk(turn.language, "user", turn.sent, turn.text)
                    self.app.store.add_talk(turn.language, "assistant", raw, reply)
            notes = self.app.run_ai_actions(actions, turn)
            if turn.material:
                kept = T("I read {name} for this answer only and kept none of it.", name=turn.material[0])
                if plan.local and self.online:
                    kept += " " + T("It was answered on this computer.")
                notes.append(dict(mark="·", text=kept))
            if problem is not None:
                why = problem.text() if isinstance(problem, llm.EngineError) else str(problem)
                notes.insert(0, dict(mark="!", text=T("The online AI did not answer, so my brain on this computer did. ({why})", why=why.rstrip("."))))
            self._tell("answer", (reply, notes))
        elif what == "error":
            self.busy = False
            self._tell("error", payload)
        elif what in ("tested", "models"):
            ok, result = payload
            if isinstance(result, llm.EngineError):
                result = result.text()
            if ok:
                self._learned(result)
            self._tell(what, (ok, result))

    def watch(self) -> None:
        """With "both" chosen: look once a minute whether the online AI can be reached (a
        bare connection, nothing is sent). The status line is then true before anybody
        asks, and the first question after the connection went does not have to find out."""
        now = time.monotonic()
        if not self.both or self.busy or self.watching or now - self.last_watch < WATCH_EVERY or not self.service().ready():
            return
        self.watching, self.last_watch = True, now
        service = self.service()
        threading.Thread(target=lambda: self._post("net", service.knock()), name="ai-net", daemon=True).start()

    def rest(self, now: float) -> None:
        """Shut the offline engine down when it has not been asked anything for a while
        (unless it is to be kept ready, or is busy fetching a model)."""
        if self.engine.process is None or self.busy or self.fetching or self.warming or self.app.settings.get("ai_keep_ready"):
            return
        if now - self.last_used > IDLE_STOP:
            self.engine.stop()

    def shutdown(self) -> None:
        self.cancel.set()
        self.engine.stop()
