"""The cat's pixel art, drawn in code.

Every frame is a 48x48 grid of palette keys ('.' is empty). The cat is built the way you
would model one in clay: rounded forms for skull, cheeks, chest and haunches, tapering
tubes for legs and tail, then markings, then the face. Because it is built from forms and
not copied from a sheet, it can move in small steps: the tail sways, the chest breathes,
the legs take real strides.

Colours are separate from shape. Every coat is the same grid of keys with another palette:
the tabby's stripes are there on the white cat too, in a colour next to white.

All side poses face right; the window mirrors them to face left. No tkinter here: plain
data and pure functions, so the art can be tested and previewed without a screen.
"""
from __future__ import annotations

import math
from functools import lru_cache

SIZE = 48
EMPTY = "."
RIM = "+"  # palette key of the light edge added by rimmed()

Frame = tuple  # SIZE strings of SIZE characters

FUR = frozenset("fdsxm")  # where markings may be painted
BODY = frozenset("fdsxmwvy")  # anything that is cat


# --------------------------------------------------------------------------- drawing

class Art:
    """A grid of palette keys with a few ways to paint rounded forms into it.
    `only` limits painting to pixels that already hold one of those keys."""

    __slots__ = ("g",)

    def __init__(self):
        self.g = [[EMPTY] * SIZE for _ in range(SIZE)]

    def ellipse(self, cx, cy, rx, ry, key, only=None) -> None:
        if rx <= 0 or ry <= 0:
            return
        g = self.g
        for y in range(max(0, int(cy - ry)), min(SIZE, int(cy + ry) + 2)):
            dy = (y + 0.5 - cy) / ry
            if abs(dy) > 1:
                continue
            half = rx * math.sqrt(1 - dy * dy)
            row = g[y]
            for x in range(max(0, int(cx - half)), min(SIZE, int(cx + half) + 2)):
                if abs(x + 0.5 - cx) <= half and (only is None or row[x] in only):
                    row[x] = key

    def ring(self, cx, cy, r_out, r_in, key, only=None, above=None) -> None:
        """A circle's edge between two radii; `above` keeps only the part higher than that y."""
        for y in range(max(0, int(cy - r_out)), min(SIZE, int(cy + r_out) + 2)):
            if above is not None and y + 0.5 > above:
                continue
            for x in range(max(0, int(cx - r_out)), min(SIZE, int(cx + r_out) + 2)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                if r_in < d <= r_out and (only is None or self.g[y][x] in only):
                    self.g[y][x] = key

    def rect(self, x0, y0, x1, y1, key, only=None) -> None:
        for y in range(max(0, int(math.ceil(y0 - 0.5))), min(SIZE, int(math.floor(y1 - 0.5)) + 1)):
            for x in range(max(0, int(math.ceil(x0 - 0.5))), min(SIZE, int(math.floor(x1 - 0.5)) + 1)):
                if only is None or self.g[y][x] in only:
                    self.g[y][x] = key

    def poly(self, points, key, only=None) -> None:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        n = len(points)
        for y in range(max(0, int(min(ys))), min(SIZE, int(max(ys)) + 1)):
            py = y + 0.5
            for x in range(max(0, int(min(xs))), min(SIZE, int(max(xs)) + 1)):
                px = x + 0.5
                inside = False
                j = n - 1
                for i in range(n):
                    xi, yi = points[i]
                    xj, yj = points[j]
                    if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                        inside = not inside
                    j = i
                if inside and (only is None or self.g[y][x] in only):
                    self.g[y][x] = key

    def tube(self, points, r0, r1, key, only=None, rings=None) -> None:
        """A rounded tube through the points, r0 thick at the start and r1 at the end.
        rings=(key, spacing, width) paints bands across it, like a tabby's tail."""
        lengths = [math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]) for i in range(len(points) - 1)]
        total = sum(lengths) or 1.0
        start = 0.0
        g = self.g
        for (ax, ay), (bx, by), length in zip(points, points[1:], lengths):
            ra = r0 + (r1 - r0) * start / total
            rb = r0 + (r1 - r0) * (start + length) / total
            r = max(ra, rb)
            dx, dy = bx - ax, by - ay
            for y in range(max(0, int(min(ay, by) - r)), min(SIZE, int(max(ay, by) + r) + 2)):
                for x in range(max(0, int(min(ax, bx) - r)), min(SIZE, int(max(ax, bx) + r) + 2)):
                    px, py = x + 0.5 - ax, y + 0.5 - ay
                    t = 0.0 if length == 0 else min(1.0, max(0.0, (px * dx + py * dy) / (length * length)))
                    if math.hypot(px - t * dx, py - t * dy) > ra + (rb - ra) * t:
                        continue
                    if only is not None and g[y][x] not in only:
                        continue
                    k = key
                    if rings is not None and ((start + t * length) % rings[1]) < rings[2]:
                        k = rings[0]
                    g[y][x] = k
            start += length

    def line(self, x0, y0, x1, y1, key, only=None, width: float = 0.5) -> None:
        self.tube(((x0, y0), (x1, y1)), width, width, key, only)

    def stamp(self, rows, x: int, y: int, only=None) -> None:
        for j, row in enumerate(rows):
            yy = y + j
            if not 0 <= yy < SIZE:
                continue
            for i, ch in enumerate(row):
                xx = x + i
                if ch != EMPTY and 0 <= xx < SIZE and (only is None or self.g[yy][xx] in only):
                    self.g[yy][xx] = ch

    def form(self, cx, cy, rx, ry, base="f", dark="d") -> None:
        """A rounded form lit from the upper left: where it lies over something already
        drawn it gets a soft dark edge, and its own lower right side is in shadow."""
        self.ellipse(cx, cy, rx + 0.9, ry + 0.9, dark, only=BODY)
        self.ellipse(cx, cy, rx, ry, dark)
        self.ellipse(cx - 0.6, cy - 0.7, rx - 0.55, ry - 0.6, base)

    def outline(self, key: str = "o") -> None:
        """A one-pixel edge around everything drawn so far."""
        g = self.g
        edge = []
        for y in range(SIZE):
            for x in range(SIZE):
                if g[y][x] != EMPTY:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < SIZE and 0 <= ny < SIZE and g[ny][nx] not in (EMPTY, key):
                        edge.append((x, y))
                        break
        for x, y in edge:
            g[y][x] = key

    def rows(self) -> Frame:
        return tuple("".join(row) for row in self.g)


# --------------------------------------------------------------------------- the face

# 'k' dark, 'e' the iris, 'h' the glint, 'l' the line of a shut eye.
EYES = {
    "open": (".kkkk.", "ehhkke", "ehkkke", "ekkkke", ".eeee."),
    "half": ("......", "kkkkkk", "ehkkke", "ekkkke", ".eeee."),
    "closed": ("......", "......", "l....l", ".llll.", "......"),
    "happy": ("......", ".llll.", "l....l", "......", "......"),
    "wide": (".kkkk.", "eeeeee", "eehkee", "eekkee", ".eeee."),
}
MOUTHS = {
    "neutral": (".ppp.", "..p..", ".k.k."),
    "open": (".ppp.", "..p..", ".kck.", "..k.."),
    "yawn": (".ppp.", ".kkk.", "kccck", "kccck", ".kkk."),
}
EARS = {
    # outer and inner triangle as (sideways, up) offsets from the head's centre
    "up": (((9.0, -2.0), (8.0, -11.2), (1.2, -6.0)), ((7.5, -4.2), (7.1, -8.8), (3.3, -5.8))),
    "low": (((9.6, -1.8), (10.8, -9.6), (2.4, -6.0)), ((8.4, -3.8), (9.4, -7.6), (4.4, -5.8))),
    "flat": (((9.6, -1.6), (12.6, -7.0), (3.6, -5.8)), ((8.6, -3.4), (10.6, -6.0), (5.4, -5.4))),
}


def _face(a: Art, hx: float, hy: float, eyes: str, mouth: str, turn: int = 0, brows=None) -> None:
    """Eyes, nose and mouth on a head centred at (hx, hy). turn=1 looks to the right:
    the features slide over and the far eye is seen narrower."""
    ey = int(round(hy - 2.5))
    left = int(round(hx - 8.5)) + 2 * turn
    right = int(round(hx + 2.5)) + 2 * turn
    eye = EYES[eyes]
    a.stamp(eye, left, ey, only=BODY)
    a.stamp(tuple(row[: 6 - turn] for row in eye) if turn else eye, right, ey, only=BODY)
    a.stamp(MOUTHS[mouth], int(round(hx - 2.5)) + 3 * turn, ey + 5, only=BODY)
    if brows == "worried":  # inner ends raised
        for side in (-1, 1):
            a.line(hx + side * 8.4, hy - 3.0, hx + side * 3.6, hy - 4.6, "l", only=BODY, width=0.45)


def _head(a: Art, hx: float, hy: float, eyes="open", mouth="neutral", ears="up", turn: int = 0, brows=None) -> None:
    """The head, front on (turn=0) or turned a little to the right (turn=1)."""
    t = 1.6 * turn
    outer, inner = EARS[ears]
    for side in (-1, 1):  # ears first: they sit behind the skull
        a.poly(tuple((hx + side * dx + t, hy + dy) for dx, dy in outer), "x")
        a.poly(tuple((hx + side * dx + t, hy + dy) for dx, dy in inner), "p")
    a.form(hx, hy, 9.6, 7.9)
    for side in (-1, 1):  # cheek fluff widens the lower face
        a.ellipse(hx + side * 8.1, hy + 2.6, 2.7, 2.9, "f" if side < 0 else "d")
        a.ellipse(hx + side * 8.1 - 0.5, hy + 2.2, 2.3, 2.5, "f")
    a.ellipse(hx + t, hy + 1.0, 6.0, 3.6, "m", only=frozenset("f"))  # a Siamese's mask; fur colour on other coats
    for dx, top, bottom in ((-2.2, -7.3, -4.7), (0.0, -7.7, -4.3), (2.2, -7.3, -4.7)):  # the tabby's M
        a.line(hx + dx + t, hy + top, hx + dx + t, hy + bottom, "s", only=FUR)
    for side in (-1, 1):
        a.line(hx + side * 9.4, hy + 0.7, hx + side * 7.0, hy + 1.1, "s", only=FUR)
        a.line(hx + side * 9.8, hy + 3.0, hx + side * 7.2, hy + 3.0, "s", only=FUR)
    a.ellipse(hx + t * 1.6, hy + 3.9, 4.3, 2.9, "w")  # muzzle
    for side in (-1, 1):  # whiskers, as light strokes across the cheeks
        a.line(hx + side * 10.0 + t, hy + 2.2, hx + side * 6.2 + t, hy + 3.2, "w", only=FUR, width=0.4)
        a.line(hx + side * 10.0 + t, hy + 4.6, hx + side * 6.2 + t, hy + 4.4, "w", only=FUR, width=0.4)
    _face(a, hx, hy, eyes, mouth, turn, brows)


# --------------------------------------------------------------------------- things it wears

def _wear(a: Art, acc, hx: float, hy: float, turn: int = 0) -> None:
    if not acc:
        return
    t = 2 * turn
    if acc == "glasses":
        for cx in (hx - 5.5 + t, hx + 5.5 + t - turn * 0.5):
            a.ring(cx, hy + 0.1, 4.3, 3.3, "j")
        a.line(hx - 1.4 + t, hy - 0.6, hx + 1.4 + t, hy - 0.6, "j")
    elif acc == "beret":
        a.ellipse(hx - 1.2, hy - 8.3, 7.6, 3.0, "R")
        a.ellipse(hx - 1.7, hy - 8.8, 7.0, 2.5, "r")
        a.line(hx - 0.6, hy - 11.2, hx - 0.2, hy - 12.6, "R", width=0.6)
    elif acc == "gradcap":
        a.rect(hx - 5.5, hy - 8.4, hx + 5.5, hy - 5.6, "j")
        a.poly(((hx - 10.5, hy - 9.0), (hx, hy - 12.6), (hx + 10.5, hy - 9.0), (hx, hy - 6.2)), "j")
        a.line(hx - 6.0, hy - 9.4, hx, hy - 11.4, "J", width=0.4)
        a.line(hx, hy - 9.4, hx + 8.6, hy - 8.6, "t", width=0.45)
        a.line(hx + 8.6, hy - 8.6, hx + 8.6, hy - 3.6, "t", width=0.45)
        a.ellipse(hx + 8.6, hy - 3.0, 1.1, 1.5, "t")
    elif acc in ("headphones", "headset"):
        a.ring(hx, hy + 0.4, 11.4, 9.9, "j", above=hy - 1.0)
        for side in (-1, 1):
            a.ellipse(hx + side * 10.6, hy + 1.2, 2.5, 3.9, "j")
            a.ellipse(hx + side * 10.9, hy + 1.2, 1.1, 2.3, "a")
        if acc == "headset":
            a.line(hx - 10.2, hy + 4.4, hx - 5.8, hy + 7.0, "j", width=0.55)
            a.ellipse(hx - 5.0, hy + 7.2, 1.4, 1.2, "a")


def _tie(a: Art, cx: float, y: float) -> None:
    a.poly(((cx - 1.6, y), (cx + 1.6, y), (cx + 1.0, y + 2.0), (cx - 1.0, y + 2.0)), "A")
    a.poly(((cx - 1.0, y + 2.0), (cx + 1.0, y + 2.0), (cx + 2.0, y + 7.2), (cx, y + 9.0), (cx - 2.0, y + 7.2)), "a")


# --------------------------------------------------------------------------- things it works with

def _item(a: Art, item, tap: int = 0) -> None:
    """What stands in front of the sitting cat. `tap` moves the paws on a keyboard."""
    if item == "laptop":
        a.rect(11.0, 32.6, 36.0, 46.0, "o")
        a.rect(12.0, 33.6, 35.0, 45.0, "g")
        a.rect(12.0, 33.6, 35.0, 34.6, "G")
        a.ellipse(23.5, 39.6, 1.9, 1.9, "a")
        a.rect(9.0, 45.6, 38.0, 47.0, "o")
        a.rect(10.0, 45.6, 37.0, 46.4, "G")
        for i, x in enumerate((17.6, 29.4)):  # paws over the top of the lid
            y = 33.0 - (0.9 if tap == i + 1 else 0.0)
            a.ellipse(x, y, 2.9, 1.9, "o")
            a.ellipse(x, y - 0.2, 2.3, 1.4, "y")
    elif item == "book":
        a.rect(10.0, 33.0, 37.0, 46.6, "o")
        a.rect(11.0, 32.2, 36.0, 33.6, "q")
        a.rect(11.0, 34.0, 23.0, 45.6, "b")
        a.rect(24.0, 34.0, 36.0, 45.6, "b")
        a.rect(11.0, 44.4, 36.0, 45.6, "B")
        a.rect(13.6, 37.0, 20.6, 38.4, "t")
        a.rect(13.6, 40.0, 18.6, 40.8, "q")
        for x in (12.8, 34.2):
            a.ellipse(x, 39.6, 2.3, 2.9, "o")
            a.ellipse(x, 39.4, 1.7, 2.3, "y")
    elif item == "easel":
        a.line(14.0, 43.0, 12.0, 47.0, "u", width=0.8)
        a.line(33.0, 43.0, 35.0, 47.0, "u", width=0.8)
        a.rect(11.0, 30.6, 36.0, 44.6, "o")
        a.rect(12.0, 31.6, 35.0, 43.6, "u")
        a.rect(13.0, 32.6, 34.0, 42.6, "q")
        a.ellipse(18.0, 36.2, 2.4, 1.9, "r")
        a.ellipse(24.4, 39.4, 2.6, 1.7, "t")
        a.ellipse(29.6, 35.8, 2.2, 2.1, "a")
        a.ellipse(20.0, 40.6, 1.5, 1.1, "b")


# --------------------------------------------------------------------------- little extras

DECO = {
    "heart": (".HH.HH.", "HHHHHHH", "HHHHHHH", ".HHHHH.", "..HHH..", "...H..."),
    "z": ("zzzz", "..z.", ".z..", "zzzz"),
    "Z": ("zzzzzz", "....z.", "...z..", "..z...", ".z....", "zzzzzz"),
    "spark": ("..t..", "..t..", "ttttt", "..t..", "..t.."),
    "dot": ("t",),
    "note": ("..nnn", "..n.n", "..n..", "..n..", "nnn..", "nnn.."),
    "bang": ("tt", "tt", "tt", "tt", "..", "tt", "tt"),
    "hg_full": ("ooooooo", "ottttto", "ottttto", ".ottto.", "..ooo..", ".oiiio.", "oiiiiio", "oiiiiio", "ooooooo"),
    "hg_half": ("ooooooo", "oiiiiio", "ottttto", ".ottto.", "..oto..", ".oitio.", "oiittio", "ottttto", "ooooooo"),
    "hg_low": ("ooooooo", "oiiiiio", "oiiiiio", ".oiiio.", "..ooo..", ".ottto.", "ottttto", "ottttto", "ooooooo"),
}


# --------------------------------------------------------------------------- poses

CX = 23.5
WALK_STEP_MS = 60  # a stride is drawn in 8 steps
WALK_STRIDE = 4.5  # how far a paw swings either side of its hip, in art pixels
# A paw on the ground travels 2 x WALK_STRIDE in half a cycle. The window has to move at
# exactly that speed, or the cat slides over the floor.
WALK_SPEED = 4 * WALK_STRIDE / (8 * WALK_STEP_MS / 1000.0)  # art pixels per second
TAILS = (  # the tail of a sitting cat, curled round its feet; the tip flicks
    ((31.0, 40.0), (37.6, 42.0), (37.0, 45.3), (30.0, 45.5)),
    ((31.0, 40.0), (37.8, 42.0), (37.8, 45.1), (31.6, 44.7)),
    ((31.0, 40.0), (38.2, 42.0), (38.8, 44.6), (34.0, 42.8)),
    ((31.0, 40.0), (37.8, 42.0), (37.8, 45.1), (31.6, 44.7)),
)
TAIL_UP = ((31.0, 41.0), (37.6, 39.4), (39.8, 32.0), (38.0, 25.6), (35.4, 25.0))
TAIL_RINGS = ("s", 3.6, 1.5)


def _draw_sit(a: Art, eyes, mouth, tail, dy, head_dy, breath, ears, paws, acc, item, tie, tap, brows) -> None:
    hx, hy = CX, 21.5 + dy + head_dy
    if tail == "up":
        a.tube(tuple((x, y + dy) for x, y in TAIL_UP), 2.2, 1.5, "x", rings=TAIL_RINGS)
    else:
        a.tube(tuple((x, y + dy) for x, y in TAILS[tail % 4]), 2.3, 1.6, "x", rings=TAIL_RINGS)
    a.form(CX, 40.2 + dy, 10.2, 6.6)  # haunches
    for side in (-1, 1):
        a.line(CX + side * 9.0, 38.2 + dy, CX + side * 6.2, 37.2 + dy, "s", only=FUR)
        a.line(CX + side * 9.6, 40.8 + dy, CX + side * 6.6, 40.0 + dy, "s", only=FUR)
        a.ellipse(CX + side * 8.9, 45.5 + dy, 3.1, 1.7, "d")  # hind paws peeking out
        a.ellipse(CX + side * 8.9 - 0.3, 45.3 + dy, 2.6, 1.3, "y")
    a.form(CX, 34.0 + dy, 6.9, 7.4 + 0.35 * breath)  # chest
    a.ellipse(CX, 33.8 + dy, 3.9, 5.7, "w")  # bib
    a.ellipse(CX, 29.4 + dy, 3.9, 1.5, "v", only=frozenset("w"))  # shadow under the chin
    if paws == "up":  # front legs thrown up
        for side in (-1, 1):
            a.tube(((CX + side * 4.2, 33.2 + dy), (CX + side * 8.6, 27.6 + dy)), 2.2, 2.0, "d")
            a.tube(((CX + side * 4.2 - 0.4, 33.0 + dy), (CX + side * 8.6 - 0.4, 27.4 + dy)), 1.8, 1.6, "f")
            a.ellipse(CX + side * 9.0, 26.8 + dy, 2.2, 2.0, "y")
    else:
        a.line(CX, 38.6 + dy, CX, 45.6 + dy, "d", width=0.7)  # the shadow between the legs
        for side in (-1, 1):
            x = CX + side * 2.85
            a.tube(((x, 37.4 + dy), (x, 44.6 + dy)), 2.15, 2.15, "d")
            a.tube(((x - 0.35, 37.2 + dy), (x - 0.35, 44.6 + dy)), 1.75, 1.75, "f")
            a.ellipse(x, 45.4 + dy, 2.7, 1.6, "v")
            a.ellipse(x - 0.3, 45.2 + dy, 2.3, 1.3, "y")
    if tie:
        _tie(a, CX, 29.6 + dy)
    _item(a, item, tap)
    _head(a, hx, hy, eyes, mouth, ears, brows=brows)
    _wear(a, acc, hx, hy)


def _leg(a: Art, hip, foot, far: bool) -> None:
    """One walking leg: thigh to knee to paw."""
    knee = ((hip[0] + foot[0]) / 2 + 0.9, (hip[1] + foot[1]) / 2 - 0.2)
    fur = "d" if far else "f"
    if not far:
        a.tube((hip, knee, foot), 2.6, 2.0, "d")
    a.tube(((hip[0] - 0.3, hip[1]), (knee[0] - 0.3, knee[1]), (foot[0] - 0.3, foot[1])), 2.2, 1.6, fur)
    a.ellipse(foot[0] + 0.5, foot[1] + 0.3, 2.5, 1.5, "v" if far else "y")


def _draw_side(a: Art, step, eyes, acc, leap) -> None:
    """Walking (step 0..7) or leaping, to the right."""
    phase = step * math.pi / 4
    dy = -4.0 if leap else (0.5 if step % 4 in (1, 2) else 0.0)
    sway = math.sin(phase)
    if leap:
        a.tube(((10.5, 32.0 + dy), (5.0, 31.4 + dy), (1.4, 29.6 + dy)), 2.2, 1.5, "x", rings=TAIL_RINGS)
    else:
        a.tube(((10.8, 31.4 + dy), (5.8, 28.4 + dy), (4.6 + sway * 0.7, 22.6 + dy), (6.8 + sway * 1.5, 17.4 + dy)), 2.2, 1.5, "x", rings=TAIL_RINGS)
    front, back = (28.8, 37.0 + dy), (14.6, 37.2 + dy)

    def foot(hip, angle):
        return (hip[0] - WALK_STRIDE * math.cos(angle), 45.6 - 2.6 * max(0.0, math.sin(angle)))

    if leap:
        far_feet = ((34.5, 41.0 + dy), (8.0, 42.4 + dy))
        near_feet = ((36.0, 42.6 + dy), (6.4, 41.0 + dy))
    else:
        far_feet = (foot(front, phase + math.pi), foot(back, phase))
        near_feet = (foot(front, phase), foot(back, phase + math.pi))
    _leg(a, (front[0] + 1.4, front[1]), far_feet[0], True)
    _leg(a, (back[0] + 1.4, back[1]), far_feet[1], True)
    a.form(21.5, 33.2 + dy, 11.8, 6.2)  # barrel
    a.form(29.6, 33.0 + dy, 5.6, 6.4)  # chest
    a.ellipse(22.0, 38.0 + dy, 8.6, 1.9, "w", only=FUR)  # belly
    for x in (13.6, 17.2, 20.8, 24.4):
        a.line(x, 27.2 + dy, x - 0.9, 31.4 + dy, "s", only=FUR)
    _leg(a, front, near_feet[0], False)
    _leg(a, back, near_feet[1], False)
    hx, hy = 35.2, 24.8 + dy
    _head(a, hx, hy, eyes, "neutral", "up", turn=1)
    _wear(a, acc, hx, hy, turn=1)


def _draw_sleep(a: Art, breath: int) -> None:
    b = breath * 0.45
    a.form(26.6, 39.6 - b, 13.8, 7.0 + b)  # curled into a loaf
    for x, top in ((22.0, 33.4), (26.0, 32.9), (30.0, 33.3), (34.0, 34.4)):
        a.line(x, top - b, x - 0.7, top + 3.3 - b, "s", only=FUR)
    a.tube(((33.6, 38.4), (36.8, 41.2), (36.6, 44.8)), 0.5, 0.5, "d", only=FUR)  # the tucked hind leg
    a.tube(((39.6, 42.0), (37.2, 45.5), (29.0, 46.0), (22.6, 45.3)), 2.1, 1.6, "x", rings=TAIL_RINGS)
    a.ellipse(22.2, 45.7, 3.0, 1.5, "v")
    a.ellipse(21.9, 45.5, 2.5, 1.2, "y")  # a front paw under the chin
    _head(a, 15.8, 38.6, "closed", "neutral", "up")


def _draw_dangle(a: Art, acc) -> None:
    """Held up by the scruff: long body, legs hanging."""
    a.tube(((27.4, 37.0), (30.8, 41.0), (30.2, 46.0)), 2.1, 1.5, "x", rings=TAIL_RINGS)
    for side in (-1, 1):  # hind legs
        a.tube(((CX + side * 3.4, 39.6), (CX + side * 4.0, 45.0)), 2.3, 2.0, "d")
        a.tube(((CX + side * 3.4 - 0.3, 39.6), (CX + side * 4.0 - 0.3, 45.0)), 1.9, 1.6, "f")
        a.ellipse(CX + side * 4.2, 45.9, 2.4, 1.3, "y")
    a.form(CX, 33.4, 6.8, 9.6)
    a.ellipse(CX, 33.2, 3.8, 7.4, "w")
    a.ellipse(CX, 25.6, 3.8, 1.5, "v", only=frozenset("w"))
    for side in (-1, 1):  # front legs held out
        a.tube(((CX + side * 4.8, 28.6), (CX + side * 9.2, 32.6)), 2.2, 1.9, "d")
        a.tube(((CX + side * 4.8 - 0.3, 28.4), (CX + side * 9.2 - 0.3, 32.4)), 1.8, 1.5, "f")
        a.ellipse(CX + side * 9.8, 33.2, 2.2, 1.9, "y")
    _head(a, CX, 17.4, "wide", "open", "flat")
    _wear(a, acc, CX, 17.4)


@lru_cache(maxsize=2048)
def render(pose: tuple, acc=None, item=None, tie: bool = False) -> Frame:
    """One finished frame for a pose from pose_at()."""
    a = Art()
    kind = pose[0]
    deco: tuple = ()
    if kind == "sit":
        _, eyes, mouth, tail, dy, head_dy, breath, ears, paws, tap, brows, deco = pose
        _draw_sit(a, eyes, mouth, tail, dy, head_dy, breath, ears, paws, acc, item, tie, tap, brows)
    elif kind == "side":
        _, step, eyes, leap, deco = pose
        _draw_side(a, step, eyes, acc, leap)
    elif kind == "sleep":
        _, breath, deco = pose
        _draw_sleep(a, breath)
    elif kind == "dangle":
        _, deco = pose
        _draw_dangle(a, acc)
    else:
        raise ValueError(f"unknown pose {pose!r}")
    a.outline()
    for name, x, y in deco:
        a.stamp(DECO[name], x, y)
    return a.rows()


# --------------------------------------------------------------------------- animation

def _sit(eyes="open", mouth="neutral", tail=0, dy=0, head_dy=0, breath=0, ears="up", paws="down", tap=0, brows=None, deco=()) -> tuple:
    return ("sit", eyes, mouth, tail, dy, head_dy, breath, ears, paws, tap, brows, deco)


# How a mood shows while the cat sits: (eyes, ears, brows, tail)
# tail: "calm" flicks now and then, "lively" keeps swaying, "still" stays wrapped
MOODS = {
    "content": ("open", "up", None, "calm"),
    "happy": ("open", "up", None, "lively"),
    "fresh": ("open", "up", None, "lively"),
    "playful": ("open", "up", None, "lively"),
    "proud": ("open", "up", None, "calm"),
    "cozy": ("open", "up", None, "calm"),
    "focused": ("half", "up", None, "still"),
    "sleepy": ("half", "low", None, "still"),
    "tired": ("half", "low", "worried", "still"),
    "worried": ("open", "low", "worried", "still"),
    "lonely": ("half", "low", "worried", "still"),
}
MOOD_NAMES = tuple(MOODS)


def pose_at(anim: str, t: int, progress: float = 0.0, mood: str = "content") -> tuple:
    """Which pose an animation shows `t` milliseconds after it started.

    `progress` (0..1) is how far a focus session has run: it picks the hourglass.
    `mood` colours the quiet poses: the eyes, the ears and how much the tail moves.
    """
    t = max(0, int(t))
    eyes, ears, brows, tail_way = MOODS.get(mood, MOODS["content"])
    blink = t % 4600 < 160
    flick = (0, 1, 2, 1)[(t // 260) % 4]
    if tail_way == "lively":
        tail = flick
    elif tail_way == "calm":
        tail = flick if 2400 <= t % 5200 < 4480 else 0  # two slow flicks, then still
    else:
        tail = 0
    breath = (t // 1700) % 2
    if anim == "sit":
        if mood in ("sleepy", "tired") and 9000 <= t % 21000 < 10300:
            return _sit("closed", "yawn", ears="flat", breath=1)
        deco = ()
        if mood in ("happy", "fresh", "proud", "cozy") and t % 7000 < 1100:
            eyes = "happy"  # a slow, pleased squint
        if mood == "proud" and 3000 <= t % 9000 < 3900:
            deco = (("spark", 38, 12), ("dot", 5, 16))
        if mood == "playful" and t % 6000 < 900:
            eyes = "wide"
        return _sit("closed" if blink else eyes, tail=tail, breath=breath, ears=ears, brows=brows, deco=deco)
    if anim == "work":
        return _sit("closed" if blink else "half", tail=tail, breath=breath, head_dy=(t // 900) % 2, tap=(0, 1, 0, 2)[(t // 190) % 4], ears=ears, brows=brows)
    if anim == "focus":
        glass = "hg_full" if progress < 0.34 else "hg_half" if progress < 0.67 else "hg_low"
        return _sit("closed" if blink else "half", tail=0, breath=breath, tap=(0, 1, 0, 2)[(t // 190) % 4], deco=((glass, 1, 37),))
    if anim == "listen":
        up = (t // 500) % 2
        return _sit("happy", tail=flick, head_dy=up, deco=(("note", 38, 9 - up), ("note", 3, 13 + up)))
    if anim == "walk":
        return ("side", (t // WALK_STEP_MS) % 8, "open", False, ())
    if anim == "leap":
        return ("side", 0, "open", True, ())
    if anim == "sleep":
        phase = (t // 750) % 3
        zs = ((("z", 26, 25),), (("z", 26, 24), ("Z", 31, 15)), (("Z", 31, 14),))[phase]
        return ("sleep", (t // 1500) % 2, zs)
    if anim == "happy":
        rise = min(5, t // 150)
        return _sit("happy", tail="up", breath=breath, deco=(("heart", 37, 11 - rise),))
    if anim == "cheer":
        up = (t // 170) % 2 == 0
        sparks = (("spark", 3, 13), ("spark", 40, 9), ("dot", 9, 8)) if up else (("spark", 5, 7), ("spark", 39, 16), ("dot", 42, 6))
        return _sit("happy", "open" if up else "neutral", tail="up", dy=-4 if up else 0, paws="up", deco=sparks)
    if anim == "talk":
        return _sit("open", "open" if (t // 200) % 2 == 0 else "neutral", tail=tail, breath=breath, ears=ears, brows=brows)
    if anim == "alert":
        mark = (("bang", 39, 5),) if (t // 350) % 2 == 0 else ()
        return _sit("wide", tail=0, deco=mark)
    if anim == "yawn":
        return _sit("closed", "yawn", ears="flat")
    if anim in ("drag", "fall"):
        return ("dangle", ())
    raise ValueError(f"unknown animation {anim!r}")


ANIMS = ("sit", "work", "focus", "listen", "walk", "leap", "sleep", "happy", "cheer", "talk", "alert", "yawn", "drag", "fall")


def frame(anim: str, t: int, acc=None, item=None, tie: bool = False, progress: float = 0.0, mood: str = "content") -> Frame:
    return render(pose_at(anim, t, progress, mood), acc, item, tie)


def mirror(rows: Frame) -> Frame:
    return tuple(row[::-1] for row in rows)


@lru_cache(maxsize=2048)
def rimmed(rows: Frame) -> Frame:
    """The frame with a one-pixel light edge around everything drawn, like a sticker:
    without it a dark outline disappears on a dark window."""
    n = len(rows)
    out = []
    for y, row in enumerate(rows):
        line = list(row)
        for x, ch in enumerate(row):
            if ch != EMPTY:
                continue
            if (
                (x > 0 and row[x - 1] != EMPTY)
                or (x + 1 < len(row) and row[x + 1] != EMPTY)
                or (y > 0 and rows[y - 1][x] != EMPTY)
                or (y + 1 < n and rows[y + 1][x] != EMPTY)
            ):
                line[x] = RIM
        out.append("".join(line))
    return tuple(out)


def first_row(rows: Frame) -> int:
    """The highest row with anything drawn in it."""
    return next((y for y, row in enumerate(rows) if row.strip(EMPTY)), len(rows))


def face_rows(mood: str = "content") -> Frame:
    """Just the head of the sitting cat, for portraits in windows."""
    rows = frame("sit", 2000, mood=mood)
    return tuple(row[10:37] for row in rows[9:31])


SIT_TOP = first_row(frame("sit", 2000))  # the row of the sitting cat's ear tips
SCRUFF_ROW = 12  # where the hand holds the cat while it is carried


# The small face for the tray and window icon is drawn by hand: at 16 pixels every pixel counts.
_ICON = (
    "................",
    "................",
    ".oo..........oo.",
    "ofpo........opfo",
    "ofppo......oppfo",
    "offfoooooooofffo",
    "offffsfssfsffffo",
    "offffffssffffffo",
    "offekffffffekffo",
    "offkkffffffkkffo",
    "owwffffppffffwwo",
    ".owwwwowwowwwwo.",
    "..oowwwwwwwwoo..",
    "....oooooooo....",
    "................",
    "................",
)


def icon_rows(size: int = 16) -> Frame:
    """The cat's face on a square canvas, for the tray and window icon."""
    if size == 16:
        return _ICON
    k = size // 16
    return tuple("".join(ch * k for ch in row) for row in _ICON for _ in range(k))


# --------------------------------------------------------------------------- colours

# o outline, f fur, d fur in shadow, s stripes, x ears and tail, y paws, m face mask,
# w white, v white in shadow, p pink, c mouth, e iris, k eye dark, h glint, l shut-eye line
COATS = {
    "grey": dict(o="#3a3f4c", f="#9da5b1", d="#7f8896", s="#5d6573", x="#9da5b1", y="#f7f5f0", m="#9da5b1",
                 w="#f7f5f0", v="#d9d6d2", p="#f4a6b0", c="#c9616f", e="#8fcf6a", k="#22252d", h="#ffffff", l="#343844"),
    "ginger": dict(o="#6b3d1c", f="#f0a95c", d="#d98f42", s="#be6f28", x="#f0a95c", y="#fff4e1", m="#f0a95c",
                   w="#fff4e1", v="#ecd8ba", p="#f4a6b0", c="#c9616f", e="#9ccf6b", k="#2a1c12", h="#ffffff", l="#5a3418"),
    "black": dict(o="#14151b", f="#3c3e4a", d="#2e3039", s="#32343e", x="#3c3e4a", y="#f4f3f6", m="#3c3e4a",
                  w="#f4f3f6", v="#d5d3da", p="#e995a3", c="#b9566a", e="#f2cf4a", k="#14151b", h="#ffffff", l="#a9abba"),
    "white": dict(o="#8f8a98", f="#f6f4f1", d="#dedad4", s="#e9e5df", x="#f6f4f1", y="#ffffff", m="#f6f4f1",
                  w="#ffffff", v="#e5e1db", p="#f6adb7", c="#cc6b7a", e="#6fb4e8", k="#2b2e3b", h="#ffffff", l="#6c6875"),
    "cream": dict(o="#5a4338", f="#f2e6d2", d="#dfd0b8", s="#e6d8c2", x="#7d5c49", y="#7d5c49", m="#c9ad95",
                  w="#f7efe0", v="#e1d3bd", p="#e9a0a6", c="#b55c68", e="#6fb4e8", k="#2a1f1a", h="#ffffff", l="#4a352b"),
}
COAT_NAMES = tuple(COATS)

THINGS = dict(
    g="#c5cbd6",  # laptop lid
    G="#e4e8ef",  # its lit edge
    j="#23252f",  # glasses, headphones, cap
    J="#4a4e5e",  # a glint on them
    t="#ffcf4a",  # sparkles, tassel, sand
    H="#ff5d73",  # heart
    z="#8fb8ff",  # sleep
    n="#b48cff",  # music note
    r="#e0524d",  # beret, paint
    R="#b23a3a",  # beret in shadow
    b="#3f6fd1",  # book cover
    B="#2f55a8",  # its lower edge
    q="#fbf8ef",  # paper
    u="#a9744a",  # wood
    i="#d8ecff",  # glass
)

ACCENTS = {
    "blue": ("#4fb3ff", "#2f7fd0"),
    "green": ("#5ed184", "#2f9a58"),
    "orange": ("#ffa94d", "#d97a1e"),
    "purple": ("#b48cff", "#7d55d6"),
    "red": ("#ff6b6b", "#c93f3f"),
}


def palette(coat: str = "grey", accent: str = "blue") -> dict:
    """Palette key -> '#rrggbb' for one coat and one accent colour."""
    light, dark = ACCENTS.get(accent, ACCENTS["blue"])
    return {**THINGS, **COATS.get(coat, COATS["grey"]), "a": light, "A": dark, RIM: "#f4f4f8"}


def check_parts() -> None:
    """Every hand-drawn stamp must be a rectangle: a short row would shift the art sideways."""
    groups = dict(EYES=EYES, MOUTHS=MOUTHS, DECO=DECO, ICON={"icon": _ICON})
    for group, parts in groups.items():
        for name, part in parts.items():
            widths = {len(row) for row in part}
            if len(widths) != 1:
                raise AssertionError(f"{group}.{name}: rows of different length {sorted(widths)}")
    assert len(_ICON) == 16 and len(_ICON[0]) == 16
