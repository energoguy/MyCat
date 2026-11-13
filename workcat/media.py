"""What is playing on this computer, for music and video suggestions.

Windows keeps a "now playing" record for every player and browser tab (the same one the
volume flyout shows): title, artist, which program, playing or paused. This module reads
that record. It does not listen to sound, it runs only if you turned the feature on, and
it never uses the network: the links it builds open in your own browser when you click.

The record lives in a WinRT interface, reached here with ctypes so the app needs nothing
installed. The interface ids and the order of their methods come from Windows' own
metadata (Windows.Media.Control).
"""
from __future__ import annotations

import ctypes
import logging
import re
import threading
import time
import urllib.parse
import uuid
from ctypes import POINTER, byref, c_int, c_long, c_uint32, c_void_p, c_wchar_p
from typing import NamedTuple

log = logging.getLogger("workcat")


class NowPlaying(NamedTuple):
    app: str  # the program's id as Windows knows it
    title: str
    artist: str
    playing: bool


# --------------------------------------------------------------------------- WinRT by hand

class _GUID(ctypes.Structure):
    _fields_ = [("d1", c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.memmove(byref(g), uuid.UUID(text).bytes_le, 16)
    return g


IID_MANAGER_STATICS = _guid("2050c4ee-11a0-57de-aed7-c97c70338245")
IID_ASYNC_INFO = _guid("00000036-0000-0000-c000-000000000046")
CLASS_MANAGER = "Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager"
STATUS_PLAYING = 4

# Slots in each interface's method table. 0-2 are IUnknown, 3-5 IInspectable.
QUERY_INTERFACE, RELEASE = 0, 2
STATICS_REQUEST_ASYNC = 6
ASYNC_INFO_STATUS = 7
ASYNC_GET_RESULTS = 8
MANAGER_CURRENT, MANAGER_SESSIONS = 6, 7
VECTOR_GET_AT, VECTOR_SIZE = 6, 7
SESSION_APP_ID, SESSION_PROPERTIES_ASYNC, SESSION_PLAYBACK_INFO = 6, 7, 9
INFO_STATUS = 7
PROPS_TITLE, PROPS_ALBUM_ARTIST, PROPS_ARTIST = 6, 8, 9

_combase = None


def _lib():
    global _combase
    if _combase is None:
        lib = ctypes.WinDLL("combase")
        lib.RoInitialize.argtypes = [c_int]
        lib.RoInitialize.restype = c_long
        lib.RoGetActivationFactory.argtypes = [c_void_p, POINTER(_GUID), POINTER(c_void_p)]
        lib.RoGetActivationFactory.restype = c_long
        lib.WindowsCreateString.argtypes = [c_wchar_p, c_uint32, POINTER(c_void_p)]
        lib.WindowsCreateString.restype = c_long
        lib.WindowsDeleteString.argtypes = [c_void_p]
        lib.WindowsDeleteString.restype = c_long
        lib.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
        lib.WindowsGetStringRawBuffer.restype = c_void_p
        _combase = lib
    return _combase


def _call(obj: c_void_p, slot: int, *args, types=()) -> int:
    """Call method number `slot` of a COM object; returns its HRESULT."""
    table = ctypes.cast(obj, POINTER(c_void_p))[0]
    address = ctypes.cast(c_void_p(table), POINTER(c_void_p))[slot]
    return ctypes.WINFUNCTYPE(c_long, c_void_p, *types)(address)(obj, *args)


def _release(obj) -> None:
    if obj is not None and obj.value:
        _call(obj, RELEASE)


def _out_object(obj: c_void_p, slot: int):
    """Call a method whose only result is another object. None if it failed or gave nothing."""
    out = c_void_p()
    if _call(obj, slot, byref(out), types=(POINTER(c_void_p),)) < 0 or not out.value:
        return None
    return out


def _out_text(obj: c_void_p, slot: int) -> str:
    handle = c_void_p()
    if _call(obj, slot, byref(handle), types=(POINTER(c_void_p),)) < 0 or not handle.value:
        return ""
    try:
        length = c_uint32(0)
        buffer = _lib().WindowsGetStringRawBuffer(handle, byref(length))
        return ctypes.wstring_at(buffer, length.value) if buffer and length.value else ""
    finally:
        _lib().WindowsDeleteString(handle)


def _wait(operation: c_void_p, timeout: float = 3.0):
    """Wait for an async WinRT operation and return its result object."""
    info = c_void_p()
    if _call(operation, QUERY_INTERFACE, byref(IID_ASYNC_INFO), byref(info), types=(POINTER(_GUID), POINTER(c_void_p))) < 0:
        raise OSError("no IAsyncInfo")
    try:
        status = c_int(0)
        deadline = time.monotonic() + timeout
        while True:
            if _call(info, ASYNC_INFO_STATUS, byref(status), types=(POINTER(c_int),)) < 0:
                raise OSError("async status failed")
            if status.value != 0:  # 0 = still running
                break
            if time.monotonic() > deadline:
                raise TimeoutError("media session did not answer")
            time.sleep(0.01)
        if status.value != 1:  # 1 = completed
            raise OSError(f"async operation ended with status {status.value}")
        return _out_object(operation, ASYNC_GET_RESULTS)
    finally:
        _release(info)


class Sessions:
    """The system's list of media sessions. Use from one thread only."""

    def __init__(self):
        lib = _lib()
        lib.RoInitialize(1)  # multithreaded; "already initialised" is fine too
        name = c_void_p()
        if lib.WindowsCreateString(CLASS_MANAGER, len(CLASS_MANAGER), byref(name)) < 0:
            raise OSError("WindowsCreateString failed")
        factory = c_void_p()
        try:
            hr = lib.RoGetActivationFactory(name, byref(IID_MANAGER_STATICS), byref(factory))
        finally:
            lib.WindowsDeleteString(name)
        if hr < 0 or not factory.value:
            raise OSError(f"media sessions are not available (0x{hr & 0xFFFFFFFF:08x})")
        operation = None
        try:
            operation = _out_object(factory, STATICS_REQUEST_ASYNC)
            if operation is None:
                raise OSError("RequestAsync failed")
            self.manager = _wait(operation)
        finally:
            _release(operation)
            _release(factory)
        if self.manager is None:
            raise OSError("no media session manager")

    def _read(self, session: c_void_p):
        info = _out_object(session, SESSION_PLAYBACK_INFO)
        status = c_int(0)
        if info is not None:
            _call(info, INFO_STATUS, byref(status), types=(POINTER(c_int),))
            _release(info)
        app = _out_text(session, SESSION_APP_ID)
        title = artist = ""
        operation = _out_object(session, SESSION_PROPERTIES_ASYNC)
        if operation is not None:
            props = None
            try:
                props = _wait(operation)
                if props is not None:
                    title = _out_text(props, PROPS_TITLE)
                    artist = _out_text(props, PROPS_ARTIST) or _out_text(props, PROPS_ALBUM_ARTIST)
            finally:
                _release(props)
                _release(operation)
        return NowPlaying(app, title.strip(), artist.strip(), status.value == STATUS_PLAYING)

    def now_playing(self):
        """The session that is playing, else the current paused one, else None."""
        best = None
        current = _out_object(self.manager, MANAGER_CURRENT)
        if current is not None:
            try:
                best = self._read(current)
            finally:
                _release(current)
        if best is not None and best.playing:
            return best
        sessions = _out_object(self.manager, MANAGER_SESSIONS)
        if sessions is None:
            return best
        try:
            count = c_uint32(0)
            _call(sessions, VECTOR_SIZE, byref(count), types=(POINTER(c_uint32),))
            for index in range(min(count.value, 12)):
                session = c_void_p()
                if _call(sessions, VECTOR_GET_AT, c_uint32(index), byref(session), types=(c_uint32, POINTER(c_void_p))) < 0 or not session.value:
                    continue
                try:
                    found = self._read(session)
                finally:
                    _release(session)
                if found.playing:
                    return found
                best = best or found
        finally:
            _release(sessions)
        return best

    def close(self) -> None:
        _release(self.manager)
        self.manager = None


class MediaWatcher(threading.Thread):
    """Asks every few seconds what is playing and puts ('media', NowPlaying or None)
    into the queue. Gives up quietly on systems without media sessions."""

    def __init__(self, out, every: float = 8.0):
        super().__init__(name="media", daemon=True)
        self.out = out
        self.every = every
        self.halt = threading.Event()

    def run(self) -> None:
        failures = 0
        sessions = None
        while not self.halt.is_set():
            try:
                if sessions is None:
                    sessions = Sessions()
                self.out.put(("media", sessions.now_playing()))
                failures = 0
            except Exception as error:  # a broken session must not take the thread down
                failures += 1
                log.info("media: %s", error)
                sessions = None
                if failures >= 5:
                    self.out.put(("media", None))
                    return
            self.halt.wait(self.every if not failures else 30.0)
        if sessions is not None:
            try:
                sessions.close()
            except Exception:
                pass

    def stop(self) -> None:
        self.halt.set()


# --------------------------------------------------------------------------- keeping the log

_MUSIC = ("spotify", "zunemusic", "music", "itunes", "aimp", "foobar", "musicbee", "winamp", "tidal", "deezer")
_VIDEO = ("vlc", "zunevideo", "mpc-", "potplayer", "netflix", "kmplayer", "mpv", "media.player", "stremio", "plex")
_WEB = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "browser", "arc")
_NAMES = (
    ("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"), ("edge", "Edge"), ("firefox", "Firefox"),
    ("opera", "Opera"), ("brave", "Brave"), ("vivaldi", "Vivaldi"), ("zunemusic", "Media Player"),
    ("media.player", "Media Player"), ("vlc", "VLC"), ("itunes", "iTunes"), ("applemusic", "Apple Music"),
    ("yandex", "Yandex Music"), ("aimp", "AIMP"), ("foobar", "foobar2000"),
)


def kind_of(app_id: str) -> str:
    """'music', 'video', 'web' (a browser tab) or 'media' for a program's session id."""
    text = app_id.lower()
    if any(word in text for word in _MUSIC):
        return "music"
    if any(word in text for word in _VIDEO):
        return "video"
    if any(word in text for word in _WEB) or re.fullmatch(r"[0-9a-f]{12,}", text):  # Firefox shows up as a hex id
        return "web"
    return "media"


def source_name(app_id: str) -> str:
    text = app_id.lower()
    for word, name in _NAMES:
        if word in text:
            return name
    if re.fullmatch(r"[0-9a-f]{12,}", text):
        return "Firefox"
    return "your player"


class PlayLog:
    """Turns the stream of "now playing" answers into finished plays in the store.
    Anything that played for less than half a minute was skipped, not listened to."""

    LEAST = 30
    GAP = 45  # no word for this long: the play is over

    def __init__(self, store):
        self.store = store
        self.current = None
        self.ended_at = 0.0

    def update(self, now: float, playing) -> None:
        on = playing is not None and playing.playing and bool(playing.title or playing.artist)
        cur = self.current
        if cur is not None and (not on or now - cur["last"] > self.GAP or (playing.app, playing.title, playing.artist) != cur["key"]):
            self._close()
        if on:
            if self.current is None:
                self.current = dict(key=(playing.app, playing.title, playing.artist), started=now, last=now)
            else:
                self.current["last"] = now

    def _close(self) -> None:
        cur, self.current = self.current, None
        if cur is None:
            return
        self.ended_at = cur["last"]
        if cur["last"] - cur["started"] >= self.LEAST:
            app, title, artist = cur["key"]
            self.store.add_play(int(cur["started"]), int(cur["last"]), app, title, artist, kind_of(app))

    def close(self) -> None:
        self._close()

    @property
    def playing(self) -> bool:
        return self.current is not None


# --------------------------------------------------------------------------- finding more

def youtube_search(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)


def spotify_search(query: str) -> str:
    return "spotify:search:" + urllib.parse.quote(query)
