"""Every text the app shows, found in the code, and whether each language file has it.

    python tools/strings.py            what is missing, left over or broken, per language
    python tools/strings.py --list     all the English texts, as a JSON list to translate

A text is anything passed to T("...") or N_("...") in workcat/. A language file is
workcat/lang/<code>.json: {"English text": "translation"}.
"""
from __future__ import annotations

import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANG = ROOT / "workcat" / "lang"


def find() -> dict:
    """English text -> where it is used ('file.py:line'), in the order of the code."""
    found: dict = {}
    for path in sorted((ROOT / "workcat").glob("*.py")):
        spots = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            first = node.args[0]
            if name in ("T", "N_") and isinstance(first, ast.Constant) and isinstance(first.value, str):
                spots.append((node.lineno, first.value))
        for line, text in sorted(spots):
            found.setdefault(text, f"{path.name}:{line}")
    return found


def fields(text: str) -> set:
    """The {placeholders} of a text, each with its format, e.g. {('m', '02d')}."""
    try:
        return {(name, spec or "") for _, name, spec, _ in string.Formatter().parse(text) if name is not None}
    except ValueError:
        return {("<broken braces>", "")}


def check(code: str) -> dict:
    """What is wrong with one language file: texts missing, entries no text uses any
    more, and translations whose placeholders differ from the English."""
    wanted = find()
    try:
        table = json.loads((LANG / f"{code}.json").read_text(encoding="utf-8"))
    except OSError:
        return dict(missing=list(wanted), extra=[], broken=[], empty=[])
    return dict(
        missing=[text for text in wanted if text not in table],
        extra=[text for text in table if text not in wanted],
        broken=[text for text in wanted if text in table and fields(table[text]) != fields(text)],
        empty=[text for text in wanted if text in table and not str(table[text]).strip()],
    )


def main() -> int:
    wanted = find()
    if "--list" in sys.argv:
        print(json.dumps(list(wanted), ensure_ascii=False, indent=1))
        return 0
    print(f"{len(wanted)} texts in the code")
    bad = 0
    for path in sorted(LANG.glob("*.json")):
        result = check(path.stem)
        problems = sum(len(v) for v in result.values())
        bad += problems
        print(f"{path.stem}: " + ("complete" if not problems else ", ".join(f"{len(v)} {k}" for k, v in result.items() if v)))
        for kind, texts in result.items():
            for text in texts:
                print(f"   {kind}: {text!r}  ({wanted.get(text, 'not in the code')})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
