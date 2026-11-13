"""Set up the offline AI from the command line. The app does exactly this from its window.

    python tools/setup_ai.py [standard|small] [--data FOLDER]

Downloads the engine (1.5 GB) and the model (3.1 GB, or 0.8 GB for "small") once, checks
them, then asks the model one question to prove it answers. Run it again after an
interruption and it continues where it stopped.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workcat import llm  # noqa: E402
from workcat.store import default_folder  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("size", nargs="?", default="standard", choices=sorted(llm.MODELS))
parser.add_argument("--data", default="")
args = parser.parse_args()

model = llm.MODELS[args.size]
engine = llm.Engine(Path(args.data) if args.data else default_folder(), app_folder=ROOT)
print(f"folder: {engine.home}")
print(f"engine installed: {engine.installed()}   model {model.name} present: {engine.ready(model.name)}", flush=True)

last = [0.0, ""]


def report(stage: str, done: int, total: int) -> None:
    now = time.monotonic()
    if stage != last[1] or now - last[0] >= 15 or done >= total:
        last[0], last[1] = now, stage
        print(f"{time.strftime('%H:%M:%S')}  {stage:7} {100 * done / max(total, 1):5.1f}%  {llm.gb(done)} of {llm.gb(total)}", flush=True)


started = time.monotonic()
try:
    engine.setup(model, report, threading.Event())
    print(f"setup finished in {time.monotonic() - started:.0f} s", flush=True)
    print("models:", engine.models(), flush=True)
    for attempt in ("first answer (the model has to load)", "second answer"):
        t0 = time.monotonic()
        first = []
        answer = engine.chat(model.name, [{"role": "user", "content": "Reply with exactly: the cat is ready"}], on_text=lambda piece: first.append(time.monotonic()) if not first else None)
        print(f"{attempt}: {answer.strip()!r} after {time.monotonic() - t0:.1f} s (first word after {first[0] - t0 if first else 0:.1f} s)", flush=True)
except llm.EngineError as error:
    print("STOPPED:", error, flush=True)
    sys.exit(1)
finally:
    engine.stop()
