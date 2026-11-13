"""Make the zip you send to other people.

    python tools/pack.py [folder to put it in]      (default: dist)

The zip holds one folder, MyCat, with the app, the start file and a short "how to
start" note in English, Russian and Uzbek. It holds nothing of yours: your settings, what
the cat learned and the offline AI live in %LOCALAPPDATA%\\MyCat, not here.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workcat import APP_NAME, __version__  # noqa: E402

TOP = (f"{APP_NAME}.pyw", f"Start {APP_NAME}.bat", "HOW TO START.txt", "README.md")
FOLDERS = {"workcat": ("*.py", "lang/*.json"), "tests": ("*.py",), "tools": ("*.py", "installer/*.cs", "installer/*.manifest")}
# Opened in Notepad by people who may have an older Windows: it wants a mark that says
# "this is UTF-8" and Windows line ends, or the Russian and Uzbek come out as nonsense.
FOR_NOTEPAD = ("HOW TO START.txt",)


def files() -> list:
    """(path on disk, name inside the zip) of everything that goes along."""
    found = [(ROOT / name, name) for name in TOP]
    for folder, patterns in FOLDERS.items():
        for pattern in patterns:
            found += [(path, path.relative_to(ROOT).as_posix()) for path in sorted((ROOT / folder).glob(pattern))]
    return found


def pack(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{APP_NAME}-{__version__}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as parcel:
        for path, name in files():
            data = path.read_bytes()
            if name in FOR_NOTEPAD:
                text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
                data = text.encode("utf-8-sig")
            parcel.writestr(f"{APP_NAME}/{name}", data)
    return target


def main() -> int:
    missing = [name for path, name in files() if not path.is_file()]
    if missing:
        print("missing:", ", ".join(missing))
        return 1
    target = pack(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist")
    with zipfile.ZipFile(target) as parcel:
        names = parcel.namelist()
    print(f"{target}  ({target.stat().st_size / 1024:.0f} KB, {len(names)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
