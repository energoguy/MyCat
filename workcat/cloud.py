"""An online AI, used only if you switch it on in Settings and give it your own key.

The cat's brain normally runs on this computer (llm.py) and sends nothing anywhere.
This is the other choice: a service on the internet answers instead. Then what you
write to the cat, and the short notes about your day that go with every question, are
sent to that service. Nothing else is, and never without the switch.

Two kinds of service are spoken to, both over plain HTTPS with what Python brings along
(the app has no add-on packages, so no SDK is used):

  Claude        Anthropic's Messages API
  OpenAI-style  the "chat completions" form that OpenAI, Gemini, OpenRouter, Groq,
                DeepSeek and many others accept

`Online.chat` has the same shape as `llm.Engine.chat`, so the rest of the app does not
care which brain answers.

The key is kept locked to your Windows account (DPAPI): the settings file never holds
it in readable form, and it is never written to the log.
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes as wt
from dataclasses import dataclass

from .i18n import N_
from .llm import AnswerFailed, Cancelled, EngineError, one_system

log = logging.getLogger("workcat")

CLAUDE_VERSION = "2026-10-21"  # the "anthropic-version" header


@dataclass(frozen=True)
class Service:
    name: str  # as shown in Settings
    kind: str  # "claude" or "openai"
    address: str  # where it answers; "" = you type it
    models: tuple = ()  # offered in the list; an OpenAI-style service is asked for its own list instead


SERVICES = {
    "claude": Service("Claude (Anthropic)", "claude", "https://api.anthropic.com", ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")),
    "openai": Service("OpenAI (ChatGPT)", "openai", "https://api.openai.com/v1"),
    "gemini": Service("Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "openrouter": Service("OpenRouter", "openai", "https://openrouter.ai/api/v1"),
    "groq": Service("Groq", "openai", "https://api.groq.com/openai/v1"),
    "deepseek": Service("DeepSeek", "openai", "https://api.deepseek.com/v1"),
    "other": Service(N_("Another service (OpenAI-style)"), "openai", ""),
}

# Claude's models under names that say what they are for. The first is the usual one.
PLAIN_NAMES = {
    "claude-opus-5-5": N_("Smartest (Opus 5.5)"),
    "claude-sonnet-5-5": N_("Balanced (Sonnet 5.5)"),
    "claude-haiku-5-5": N_("Fastest and cheapest (Haiku 5.5)"),
}

# How a key begins says whose it is, for the services that mark theirs. (A plain "sk-"
# does not: several services use it.)
_KEY_MARKS = (("sk-ant-", "claude"), ("sk-or-", "openrouter"), ("gsk_", "groq"), ("AIza", "gemini"), ("sk-proj-", "openai"))


def guess_service(key: str) -> str:
    """The service a key belongs to, going by how it begins; "" when that does not say."""
    key = key.strip()
    return next((service for mark, service in _KEY_MARKS if key.startswith(mark)), "")


# Names in a service's list that are not for talking to: they draw, listen, speak or sort.
_NOT_FOR_CHAT = re.compile(
    r"embed|whisper|tts|audio|speech|transcri|image|dall|imagen|veo|sora|moderation|realtime|rerank|guard|search|computer|codex|instruct|vision|ocr|aqa|babbage|davinci|-live|robotics",
    re.I,
)
# What to pick when nobody has picked: per service, the first of these that the list
# has, and of several the newest. A quick, inexpensive, capable model each time.
_PREFERRED = {
    "openai": (r"^gpt-[\d.]+-mini$", r"^gpt-[\d.]+$", r"^gpt-[\d.]+o-mini$", r"^gpt-", r"^chatgpt-"),
    "gemini": (r"^gemini-[\d.]+-flash$", r"^gemini-[\d.]+-pro$", r"^gemini-.*flash", r"^gemini-"),
    "groq": (r"versatile", r"llama.*70b", r"llama"),
    "deepseek": (r"^deepseek-chat$", r"^deepseek-"),
    "openrouter": (r"^openrouter/auto$", r"^anthropic/claude-sonnet", r"^openai/gpt-[\d.]+-mini$"),
}


def _newness(name: str) -> tuple:
    """Sorts model names so that the one with the highest numbers comes last."""
    return tuple(float(number) for number in re.findall(r"\d+(?:\.\d+)?", name)), -len(name)


def pick_default(service: str, names) -> str:
    """The model to use from a service's own list when the person has chosen none."""
    known = SERVICES.get(service)
    if known is not None and known.models:
        return known.models[0]
    names = [name for name in names if name]
    for_chat = [name for name in names if not _NOT_FOR_CHAT.search(name)] or names
    for pattern in _PREFERRED.get(service, ()):
        found = [name for name in for_chat if re.search(pattern, name, re.I)]
        if found:
            return max(found, key=_newness)
    return for_chat[0] if for_chat else ""


# --------------------------------------------------------------------------- keeping the key

class _Blob(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _crypt(function: str, data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, result = _blob(data), _Blob()
    call = getattr(crypt32, function)
    call.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_Blob)]
    call.restype = wt.BOOL
    if not call(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), function)
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(result.data)


def lock(key: str) -> str:
    """A key as it is stored: readable only by the same person on the same computer."""
    if not key:
        return ""
    return base64.b64encode(_crypt("CryptProtectData", key.encode("utf-8"))).decode("ascii")


def unlock(stored: str) -> str:
    """The key again. '' if it was stored by someone else, or elsewhere, or is damaged."""
    if not stored:
        return ""
    try:
        return _crypt("CryptUnprotectData", base64.b64decode(stored)).decode("utf-8")
    except (OSError, ValueError):
        return ""


# --------------------------------------------------------------------------- talking

class _TryAgain(AnswerFailed):
    """The service was busy or broke off: worth one more try."""


def _problem(status: int, detail: str) -> EngineError:
    """What an HTTP error from a service means, in words for the person."""
    low = detail.lower()
    if status in (401, 403):
        return EngineError(N_("The service did not accept the key. Is it a key for this service, and typed in full?"))
    if status == 402 or (status in (400, 429) and any(word in low for word in ("quota", "credit", "billing", "balance"))):
        return EngineError(N_("The service says this account has no credit left."))
    if status == 404:
        return EngineError(N_("The service does not know this model, or its address is wrong. Please check both in the AI brain tab."))
    if status == 429 or status >= 500:
        return _TryAgain(f"{status} {detail}"[:300])
    return EngineError(N_("The service refused the question: {detail}"), detail=detail[:300] or str(status))


def _detail(body: str) -> str:
    """The message inside a service's error answer."""
    try:
        data = json.loads(body)
    except ValueError:
        return " ".join(body.split())[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error)
    if isinstance(data, list) and data and isinstance(data[0], dict):  # Gemini wraps its errors in a list
        return _detail(json.dumps(data[0]))
    return str(error or data)[:300]


def strict(schema):
    """The answer's shape with 'no other fields' said out loud at every level: services
    that hold the model to a shape want to be told."""
    if isinstance(schema, dict):
        out = {key: strict(value) for key, value in schema.items()}
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out
    if isinstance(schema, list):
        return [strict(item) for item in schema]
    return schema


class Online:
    """One online service, with one key and one model."""

    local = False  # big models need no help with alphabets, and nothing runs on this computer
    process = None

    def __init__(self, service: str, key: str, model: str = "", address: str = ""):
        self.service = SERVICES.get(service) or SERVICES["other"]
        self.key = key.strip()
        self.address = (address.strip() or self.service.address).rstrip("/")
        self.model = model.strip() or (self.service.models[0] if self.service.models else "")

    # the same questions the offline engine answers
    def installed(self) -> bool:
        return True

    def ready(self, _model: str = "") -> bool:
        return bool(self.key and self.address and self.model)

    def reachable(self) -> bool:
        """There is enough to ask the service something: which models it has, at least."""
        return bool(self.key and self.address)

    def knock(self, timeout: float = 2.0) -> bool:
        """Whether the service's door can be reached at all: a bare connection to it, with
        nothing sent. It takes a moment, where a question into the void takes its whole
        patience: so a lost connection is noticed in two seconds. (Where this computer
        reaches the internet through a proxy the door cannot be knocked on from here, and
        is taken to be there: the question itself will tell.)"""
        try:
            parts = urllib.parse.urlsplit(self.address)
            if not parts.hostname:
                return False
            if urllib.request.getproxies().get(parts.scheme):
                return True
            socket.create_connection((parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)), timeout=timeout).close()
            return True
        except (OSError, ValueError):
            return False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _open(self, path: str, payload=None, timeout: float = 60):
        headers = {"Content-Type": "application/json", "User-Agent": "MyCat"}
        if self.service.kind == "claude":
            headers.update({"x-api-key": self.key, "anthropic-version": CLAUDE_VERSION})
        else:
            headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.address + path, data=data, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            with error:
                body = error.read().decode("utf-8", "replace")
            raise _problem(error.code, _detail(body)) from None
        except (OSError, ValueError) as error:  # no network, a wrong address
            log.info("online service not reached: %s", type(error).__name__)
            raise EngineError(N_("No connection to the online service. Is the internet working, and is the address right?")) from None

    def models(self) -> list:
        """The models to choose from: the service's own list, asked for with this key.
        (Claude's are few and known, so they are not asked for.)"""
        if self.service.models:
            return list(self.service.models)
        with self._open("/models", timeout=20) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        rows = data.get("data") if isinstance(data, dict) else data
        names = sorted({str(row.get("id") or "").removeprefix("models/") for row in rows or [] if isinstance(row, dict)} - {""})
        return names

    def chat(self, model: str, messages: list, schema=None, on_text=None, cancel=None, options=None, on_again=None, tries: int = 2) -> str:
        """Send a conversation, return the whole answer; on_text gets it piece by piece.
        A busy service is asked once more after a moment (`on_again` is called first)."""
        cancel = cancel or threading.Event()
        ask = self._claude if self.service.kind == "claude" else self._openai
        for attempt in range(1, tries + 1):
            try:
                return ask(model or self.model, messages, schema, on_text, cancel)
            except _TryAgain as error:
                log.info("the online service asked us to try again (%s), try %d of %d", error.detail, attempt, tries)
                if attempt == tries:
                    raise EngineError(N_("The service is busy right now. Please try again in a moment.")) from None
                if on_again:
                    on_again()
                time.sleep(1.5)
        return ""

    def _events(self, response, cancel):
        """The JSON objects of a stream of server-sent events."""
        try:
            for raw in response:
                if cancel.is_set():
                    raise Cancelled()
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    yield json.loads(data)
                except ValueError:
                    continue
        except OSError:
            raise _TryAgain("the connection broke off") from None

    def _claude(self, model: str, messages: list, schema, on_text, cancel) -> str:
        # The instructions come in two parts (see llm.one_system). The lasting one is
        # marked for the service's own cache: it then reads that part once and, for the
        # questions that follow within a few minutes, starts sooner and charges less.
        system = [{"type": "text", "text": m["content"]} for m in messages if m["role"] == "system" and m["content"]]
        if len(system) > 1:
            system[0]["cache_control"] = {"type": "ephemeral"}
        payload = {
            "model": model,
            "max_tokens": 8000,  # room to think first, and for a text written out in full
            "stream": True,
            "messages": [m for m in messages if m["role"] != "system"],
            "output_config": {"effort": "low"},  # a quick, friendly answer, not an essay
        }
        if system:
            payload["system"] = system
        if schema is not None:
            payload["output_config"]["format"] = {"type": "json_schema", "schema": strict(schema)}
        try:
            response = self._open("/v1/messages", payload)
        except EngineError as error:
            # An older model may not take output_config: ask again in the plainest way. The
            # instructions already say which shape to answer in, and the reader forgives.
            if isinstance(error, _TryAgain) or "detail" not in error.values or "output_config" not in str(error.values["detail"]):
                raise
            payload.pop("output_config")
            response = self._open("/v1/messages", payload)
        pieces = []
        with response:
            for event in self._events(response, cancel):
                kind = event.get("type")
                if kind == "content_block_delta" and (event.get("delta") or {}).get("type") == "text_delta":
                    piece = event["delta"].get("text") or ""
                    if piece:
                        pieces.append(piece)
                        if on_text:
                            on_text(piece)
                elif kind == "error":
                    raise _TryAgain(_detail(json.dumps(event)))
                elif kind == "message_stop":
                    break
        return "".join(pieces)

    def _openai(self, model: str, messages: list, schema, on_text, cancel) -> str:
        payload = {"model": model, "messages": one_system(messages), "stream": True}
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._open("/chat/completions", payload)
        except EngineError as error:
            # Not every service knows "answer in JSON": without it the instructions still ask for it.
            if isinstance(error, _TryAgain) or "detail" not in error.values or "response_format" not in payload:
                raise
            payload.pop("response_format")
            response = self._open("/chat/completions", payload)
        pieces = []
        with response:
            for event in self._events(response, cancel):
                if isinstance(event.get("error"), dict):
                    raise _TryAgain(_detail(json.dumps(event)))
                choices = event.get("choices") or [{}]
                piece = (choices[0].get("delta") or {}).get("content") or ""
                if piece:
                    pieces.append(piece)
                    if on_text:
                        on_text(piece)
        return "".join(pieces)
