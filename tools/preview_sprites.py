"""Draw every pose of the cat into one PNG, to check the art by eye.

    python tools/preview_sprites.py [out.png] [scale] [only]

`only` is "sit", "move" or "coats" to draw just that group, larger. Needs Pillow.
The app itself does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from workcat import sprites  # noqa: E402

PAD = 8
LABEL = 13

# (label, animation, time in ms, accessory, item, tie, progress, coat, accent)
SIT = [
    ("sit", "sit", 500, None, None, False, 0, "grey", "blue"),
    ("blink", "sit", 50, None, None, False, 0, "grey", "blue"),
    ("tail flick", "sit", 2930, None, None, False, 0, "grey", "blue"),
    ("talk", "talk", 0, None, None, False, 0, "grey", "blue"),
    ("yawn", "yawn", 0, None, None, False, 0, "grey", "blue"),
    ("alert", "alert", 0, None, None, False, 0, "grey", "blue"),
    ("happy", "happy", 700, None, None, False, 0, "grey", "blue"),
    ("cheer up", "cheer", 0, None, None, False, 0, "grey", "blue"),
    ("cheer down", "cheer", 200, None, None, False, 0, "grey", "blue"),
    ("code", "work", 500, "glasses", "laptop", False, 0, "grey", "green"),
    ("code tap", "work", 200, "glasses", "laptop", False, 0, "grey", "green"),
    ("office", "work", 500, None, "laptop", True, 0, "grey", "blue"),
    ("office sit", "sit", 500, None, None, True, 0, "grey", "blue"),
    ("design", "work", 500, "beret", "easel", False, 0, "grey", "orange"),
    ("study", "work", 500, "gradcap", "book", False, 0, "grey", "purple"),
    ("call", "sit", 500, "headset", None, False, 0, "grey", "blue"),
    ("listen", "listen", 0, "headphones", None, False, 0, "grey", "purple"),
    ("focus", "focus", 500, "glasses", "laptop", False, 0.5, "grey", "green"),
]
MOVE = [(f"walk {i}", "walk", i * 85, None, None, False, 0, "grey", "blue") for i in range(8)] + [
    ("leap", "leap", 0, None, None, False, 0, "grey", "blue"),
    ("drag", "drag", 0, None, None, False, 0, "grey", "blue"),
    ("sleep a", "sleep", 0, None, None, False, 0, "grey", "blue"),
    ("sleep b", "sleep", 1600, None, None, False, 0, "grey", "blue"),
    ("walk+glasses", "walk", 0, "glasses", None, False, 0, "grey", "blue"),
    ("mirror walk", "walk", 170, None, None, False, 0, "ginger", "blue"),
]
COATS = [(coat, "sit", 500, None, None, False, 0, coat, "blue") for coat in sprites.COAT_NAMES] + [
    (coat + " walk", "walk", 170, None, None, False, 0, coat, "blue") for coat in sprites.COAT_NAMES
] + [(coat + " sleep", "sleep", 0, None, None, False, 0, coat, "blue") for coat in sprites.COAT_NAMES] + [
    ("black code", "work", 500, "glasses", "laptop", False, 0, "black", "green"),
    ("cream happy", "happy", 700, None, None, False, 0, "cream", "blue"),
    ("ginger study", "work", 500, "gradcap", "book", False, 0, "ginger", "purple"),
]
# the same, with a mood at the end
MOODS = [(mood, "sit", 2000, None, None, False, 0, "grey", "blue", mood) for mood in sprites.MOOD_NAMES] + [
    ("happy squint", "sit", 500, None, None, False, 0, "grey", "blue", "happy"),
    ("proud sparkle", "sit", 3200, None, None, False, 0, "grey", "blue", "proud"),
    ("sleepy yawn", "sit", 9500, None, None, False, 0, "grey", "blue", "sleepy"),
    ("playful", "sit", 300, None, None, False, 0, "ginger", "blue", "playful"),
    ("tired at work", "work", 500, "glasses", "laptop", False, 0, "grey", "green", "tired"),
    ("worried black", "sit", 2000, None, None, False, 0, "black", "blue", "worried"),
    ("lonely cream", "sit", 2000, None, None, False, 0, "cream", "blue", "lonely"),
]
GROUPS = {"sit": SIT, "move": MOVE, "coats": COATS, "moods": MOODS}


def draw(rows, pal, bg, scale):
    cell = sprites.SIZE * scale
    img = Image.new("RGB", (cell, cell), bg)
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == sprites.EMPTY:
                continue
            colour = tuple(int(pal[ch][i:i + 2], 16) for i in (1, 3, 5))
            for dy in range(scale):
                for dx in range(scale):
                    px[x * scale + dx, y * scale + dy] = colour
    return img


def main(out: str, scale: int, only: str) -> None:
    sprites.check_parts()
    shots = GROUPS[only] if only else SIT + MOVE + COATS + MOODS
    cell = sprites.SIZE * scale
    cols = max(1, min(len(shots), 1500 // (cell + PAD)))
    lines = (len(shots) + cols - 1) // cols
    backgrounds = [(238, 240, 244), (40, 44, 56)]
    sheet = Image.new("RGB", (PAD + cols * (cell + PAD), PAD + lines * len(backgrounds) * (cell + LABEL + PAD)), (255, 255, 255))
    pen = ImageDraw.Draw(sheet)
    for b, bg in enumerate(backgrounds):
        for i, shot in enumerate(shots):
            label, anim, t, acc, item, tie, progress, coat, accent = shot[:9]
            rows = sprites.rimmed(sprites.frame(anim, t, acc, item, tie, progress, shot[9] if len(shot) > 9 else "content"))
            if label.startswith("mirror"):
                rows = sprites.mirror(rows)
            x = PAD + (i % cols) * (cell + PAD)
            y = PAD + (b * lines + i // cols) * (cell + LABEL + PAD)
            sheet.paste(draw(rows, sprites.palette(coat, accent), bg, scale), (x, y))
            pen.text((x, y + cell + 1), label, fill=(60, 60, 70))
    sheet.save(out)
    print("saved", out, sheet.size)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sprites.png", int(sys.argv[2]) if len(sys.argv) > 2 else 3, sys.argv[3] if len(sys.argv) > 3 else "")
