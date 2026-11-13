"""The cat's voice: a purr when it is petted, a small trill when you say hello after a
while, and a soft "mew" with a reminder.

They are off unless switched on in Settings. No sound files travel with the app: each
sound is worked out here, sample by sample, the way a cat makes it, and written into
the data folder the first time it is needed. Windows plays it (winsound) without
waiting for it to end.

How a cat makes them, which is what is copied here:

  purr   Not a hum. The voice box twitches open about 25 times a second, and each
         twitch is a small thump that rings on in the chest and mouth for a few
         hundredths of a second. It goes on breathing in and breathing out, a little
         faster and airier on the way in, with the briefest dip where the breath turns.
  mew    A voice like ours, only smaller: a buzz from the throat whose pitch rises and
         falls again, shaped by a mouth that opens and closes ("m-e-a-u"). A small
         animal has a short throat, so everything sits higher than in a human voice.
  trill  A purr and a voice at once: a short rising "mrrp".
"""
from __future__ import annotations

import logging
import math
import random
import struct
import threading
import wave
from pathlib import Path

log = logging.getLogger("workcat")

RATE = 22050  # samples a second: plenty for sounds this soft
TAKE = 2  # raised whenever a sound is made differently, so files kept from before are made anew


def _ease(x: float) -> float:
    """0..1 in, 0..1 out, gentle at both ends."""
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


# --------------------------------------------------------------------------- a voice

# The mouth in five positions: (where it rings in Hz, how broadly, how strongly), three times.
MOUTH = {
    "m": ((430.0, 170.0, 0.90), (1500.0, 300.0, 0.10), (3400.0, 500.0, 0.03)),  # closed: dull, through the nose
    "i": ((780.0, 200.0, 1.00), (3250.0, 380.0, 0.55), (4700.0, 520.0, 0.18)),
    "a": ((1550.0, 300.0, 1.00), (2750.0, 380.0, 0.60), (4600.0, 550.0, 0.20)),  # wide open
    "o": ((1050.0, 260.0, 1.00), (2000.0, 340.0, 0.42), (4100.0, 500.0, 0.10)),
    "u": ((650.0, 200.0, 0.85), (1500.0, 300.0, 0.22), (3700.0, 500.0, 0.04)),  # nearly closed again
    "r": ((900.0, 260.0, 1.00), (1900.0, 340.0, 0.40), (3600.0, 500.0, 0.08)),
    "e": ((1300.0, 300.0, 1.00), (2900.0, 380.0, 0.50), (4500.0, 520.0, 0.15)),
}


def _mouth_at(stages, u: float) -> list:
    """The mouth at moment u (0..1), gliding between the positions named in `stages`."""
    for (u0, a), (u1, b) in zip(stages, stages[1:]):
        if u <= u1:
            share = _ease((u - u0) / (u1 - u0)) if u1 > u0 else 1.0
            return [tuple(x + (y - x) * share for x, y in zip(p, q)) for p, q in zip(MOUTH[a], MOUTH[b])]
    return list(MOUTH[stages[-1][1]])


def _voice(seconds: float, pitch, stages, loud, breath: float, seed: int, roll=None) -> list:
    """A voiced sound. `pitch(u)` is its height in Hz as it goes (u from 0 to 1),
    `stages` the mouth's positions, `loud(u)` how strong it is, `breath` how much air
    is heard in it, `roll(t, u)` an extra wobble of the strength (for the trill)."""
    noise = random.Random(seed)
    total = int(RATE * seconds)
    out = [0.0] * total
    phase = 0.0
    wander = 0.0  # no living voice holds a pitch dead still
    hiss = 0.0
    gains: list = []
    top = 0.45 * RATE
    for i in range(total):
        u = i / total
        t = i / RATE
        wander += 0.004 * (noise.uniform(-1.0, 1.0) - wander)
        f0 = pitch(u) * (1.0 + 0.4 * wander + 0.004 * math.sin(2.0 * math.pi * 5.5 * t))
        phase += 2.0 * math.pi * f0 / RATE
        if i % 8 == 0:  # the mouth moves slowly: its shape is worked out again a few thousand times a second
            shape = _mouth_at(stages, u)
            gains = []
            k = 1
            while k * f0 < top and k <= 14:
                f = k * f0
                gain = 0.012
                for centre, width, weight in shape:
                    d = (f - centre) / width
                    gain += weight / (1.0 + d * d)
                gains.append(gain / k ** 1.15)  # the buzz from the throat is weaker the higher it goes
                k += 1
            # The mouth changes the colour of the sound, not its strength: that is `loud`'s say.
            power = math.sqrt(sum(gain * gain for gain in gains)) or 1.0
            gains = [gain / power for gain in gains]
        sample = 0.0
        for k, gain in enumerate(gains, start=1):
            sample += gain * math.sin(k * phase)
        white = noise.uniform(-1.0, 1.0)
        hiss += 0.5 * (white - hiss)
        strength = loud(u) * (roll(t, u) if roll else 1.0)
        out[i] = strength * (sample + breath * (0.6 + u) * (white - hiss))
    return out


def _mew() -> list:
    """A small "mew": up, and softly down again."""
    pitch = lambda u: 640.0 + 240.0 * math.sin(math.pi * u ** 0.72) - 100.0 * u
    stages = ((0.0, "m"), (0.10, "m"), (0.26, "i"), (0.50, "a"), (0.80, "o"), (1.0, "u"))
    loud = lambda u: _ease(u / 0.13) * (0.55 + 0.45 * math.sin(math.pi * u ** 0.85)) * _ease((1.0 - u) / 0.38)  # loudest with the mouth open
    return _voice(0.52, pitch, stages, loud, breath=0.035, seed=3)


def _trill() -> list:
    """"Mrrp": a rising voice that rolls like a purr and stops short."""
    pitch = lambda u: 380.0 + 300.0 * u ** 1.6
    stages = ((0.0, "m"), (0.22, "m"), (0.62, "r"), (1.0, "e"))
    loud = lambda u: _ease(u / 0.14) * _ease((1.0 - u) / 0.09)
    roll = lambda t, u: 1.0 - (0.72 - 0.5 * u) * (0.5 + 0.5 * math.cos(2.0 * math.pi * 27.0 * t))
    return _voice(0.34, pitch, stages, loud, breath=0.03, seed=5, roll=roll)


# --------------------------------------------------------------------------- the purr

# What one twitch of the voice box sets ringing: (Hz, seconds until it has died away to a third, strength).
# A real purr is deepest below 200 Hz, but the small speakers of a laptop play almost
# nothing down there. So the weight is put on what they can play, a few hundred Hz, and
# the deep part is kept for speakers and headphones that have it.
RING = ((150.0, 0.0110, 0.50), (310.0, 0.0085, 1.00), (640.0, 0.0050, 0.66), (1250.0, 0.0028, 0.26), (2300.0, 0.0016, 0.08))
THUMP = 0.036  # seconds one twitch is heard for


def _thump(bend: float) -> list:
    """One twitch, ringing. `bend` makes it a touch higher or lower: no two are alike."""
    out = []
    for n in range(int(RATE * THUMP)):
        x = n / RATE
        value = 0.0
        for hz, fade, part in RING:
            value += part * math.exp(-x / fade) * math.sin(2.0 * math.pi * hz * bend * x)
        out.append(min(1.0, x / 0.0016) * value)  # it starts fast, but not from nothing: no click
    return out


def _purr(breaths=None) -> list:
    """Breathing in and out, twice by default: each breath a run of small thumps."""
    noise = random.Random(7)  # the same purr every time
    # (seconds, thumps a second, how strong, how much air is heard): in, out, in, out
    breaths = breaths or ((0.62, 25.0, 0.80, 0.38), (0.86, 22.5, 1.00, 0.18), (0.60, 25.0, 0.78, 0.38), (0.92, 22.0, 0.94, 0.18))
    turn = 0.07  # the breath turning round
    total = int(RATE * (sum(b[0] for b in breaths) + turn * (len(breaths) - 1) + THUMP + 0.02))
    out = [0.0] * total
    pulse = [0.0] * total  # how lately a thump came: the air is heard most just then
    air = [0.0] * total
    thumps = {bend: _thump(bend) for bend in (0.97, 0.985, 1.0, 1.015, 1.03)}
    bends = list(thumps)
    start = 0.0
    for seconds, rate, strong, airy in breaths:
        first, last = int(start * RATE), min(total, int((start + seconds) * RATE))
        for i in range(first, last):
            air[i] = airy * math.sin(math.pi * (i - first) / max(1, last - first)) ** 0.5
        t = 0.0
        while t < seconds:
            swell = math.sin(math.pi * t / seconds) ** 0.45  # a breath swells and sinks
            strength = strong * swell * noise.uniform(0.88, 1.08)
            shape = thumps[noise.choice(bends)]
            at = int((start + t) * RATE)
            for n, value in enumerate(shape):
                if at + n >= total:
                    break
                out[at + n] += strength * value
                pulse[at + n] += swell * math.exp(-n / (RATE * 0.010))
            t += noise.uniform(0.965, 1.035) / rate  # never quite even
        start += seconds + turn
    low = slow = 0.0
    for i in range(total):  # the air: a soft hiss, kept to the middle of what the ear hears
        white = noise.uniform(-1.0, 1.0)
        low += 0.45 * (white - low)
        slow += 0.06 * (low - slow)
        out[i] += 1.6 * air[i] * (0.3 + 0.7 * min(1.0, pulse[i])) * (low - slow)
    fade_in, fade_out = int(RATE * 0.05), int(RATE * 0.22)
    for i in range(min(fade_in, total)):
        out[i] *= i / fade_in
    for i in range(min(fade_out, total)):
        out[total - 1 - i] *= i / fade_out
    return out


def _level(samples: list, peak: float) -> list:
    """The same sound with its loudest moment at `peak`, and resting on zero."""
    rest = sum(samples) / len(samples)
    loudest = max(abs(x - rest) for x in samples) or 1.0
    return [(x - rest) * peak / loudest for x in samples]


def _greet() -> list:
    """Hello after a while: a trill, then the purr (one breath in and out)."""
    purr = _purr(((0.62, 25.0, 0.80, 0.38), (0.95, 22.5, 1.00, 0.18)))
    # A held note sounds far louder than a run of thumps of the same height: the trill is kept low.
    return _level(_trill(), 0.42) + [0.0] * int(RATE * 0.05) + _level(purr, 1.0)


MAKERS = {"purr": _purr, "greet": _greet, "mew": _mew}
LEVEL = {"purr": 0.60, "greet": 0.60, "mew": 0.34}  # how loud each is at its loudest, 1 being all the way: these are soft sounds


def write(name: str, path: Path) -> Path:
    """Make the sound called `name` and save it as a .wav file."""
    samples = _level(MAKERS[name](), LEVEL[name])
    frames = b"".join(struct.pack("<h", int(32767 * x)) for x in samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    with wave.open(str(part), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames)
    part.replace(path)  # there only once it is whole
    return path


class Sounds:
    def __init__(self, folder: Path):
        self.folder = Path(folder) / "sounds"
        self.lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.folder / f"{name}-{TAKE}.wav"

    def prepare(self) -> None:
        """Make every sound that is not there yet, in the background, and clear away the
        files of older versions. Called when sounds are switched on, so the first purr
        does not have to be worked out at the moment the cat is petted."""
        threading.Thread(target=self._prepare, name="sounds", daemon=True).start()

    def _prepare(self) -> None:
        try:
            for name in MAKERS:
                self._made(name)
            keep = {self.path(name).name for name in MAKERS}
            for old in self.folder.glob("*.wav"):
                if old.name not in keep:
                    old.unlink(missing_ok=True)
        except Exception:  # a full disk, a folder that cannot be written: then there is no sound
            log.info("could not make the sounds", exc_info=True)

    def _made(self, name: str) -> Path:
        path = self.path(name)
        with self.lock:  # one at a time: two threads never write the same file
            if not path.is_file():
                write(name, path)
        return path

    def play(self, name: str) -> bool:
        """Start playing a sound and return at once. False if it cannot be played."""
        if name not in MAKERS:
            return False
        if self.path(name).is_file():
            return self._start(self.path(name))
        threading.Thread(target=lambda: self._start(self._made(name)), name="sound", daemon=True).start()  # heard a moment later, the first time
        return True

    def _start(self, path: Path) -> bool:
        try:
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return True
        except Exception:  # no sound card, no winsound: a sound is never worth an error
            log.info("could not play %s", path.name, exc_info=True)
            return False
