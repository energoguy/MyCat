"""Where the cat may sit: on top of the window you work in, or on the taskbar.

Pure geometry over rectangles. The Win32 calls live in win32.py; nothing here touches
the screen, so it runs in tests on any machine.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Seat:
    kind: str  # "window" or "floor"
    hwnd: int  # 0 for the floor
    y: int  # the line the cat's feet stand on
    left: int  # the cat's centre may be anywhere in left..right
    right: int

    def clamp(self, x: float) -> int:
        return int(min(max(x, self.left), self.right))


def monitor_at(x: int, y: int, monitors: list):
    """The monitor holding a point, else the nearest one."""
    for m in monitors:
        if m.rect.contains(x, y):
            return m

    def distance(m) -> int:
        dx = max(m.rect.left - x, 0, x - (m.rect.right - 1))
        dy = max(m.rect.top - y, 0, y - (m.rect.bottom - 1))
        return dx * dx + dy * dy

    return min(monitors, key=distance) if monitors else None


def monitor_of(rect, monitors: list):
    """The monitor that holds most of a rectangle."""
    def overlap(m) -> int:
        w = min(rect.right, m.rect.right) - max(rect.left, m.rect.left)
        h = min(rect.bottom, m.rect.bottom) - max(rect.top, m.rect.top)
        return max(w, 0) * max(h, 0)

    best = max(monitors, key=overlap, default=None)
    if best is not None and overlap(best) > 0:
        return best
    return monitor_at((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2, monitors)


def outer_edge(x: int, y: int, monitors: list, reach: int):
    """('left' | 'right', monitor) if the point is within `reach` of a side of the screen
    with no other monitor beyond it; else None. That is where the cat can tuck itself
    away: at an edge between two monitors it would only hang over onto the other one."""
    monitor = monitor_at(x, y, monitors)
    if monitor is None:
        return None
    for side, edge in (("left", monitor.rect.left), ("right", monitor.rect.right)):
        near = x - edge <= reach if side == "left" else edge - x <= reach
        if not near:
            continue
        beyond = edge - 1 if side == "left" else edge  # the first pixel past that side
        neighbour = any(
            other is not monitor and other.rect.left <= beyond < other.rect.right and other.rect.top < monitor.rect.bottom and other.rect.bottom > monitor.rect.top
            for other in monitors
        )
        if not neighbour:
            return side, monitor
    return None


def _span(left: int, right: int, margin: int) -> tuple:
    """A stretch narrowed by `margin` on both sides; a short one shrinks to its middle."""
    if right - left <= 2 * margin:
        mid = (left + right) // 2
        return mid, mid
    return left + margin, right - margin


def floor_seat(monitor, margin: int, within=None) -> Seat:
    """The top of the taskbar. `within` narrows it to the width of a window above it."""
    left, right = monitor.work.left, monitor.work.right
    if within is not None:
        lo, hi = max(left, within[0]), min(right, within[1])
        if hi - lo >= 2 * margin:
            left, right = lo, hi
    left, right = _span(left, right, margin)
    return Seat("floor", 0, monitor.work.bottom, left, right)


def window_seat(hwnd: int, rect, monitors: list, need: int, margin: int):
    """The top edge of a window, if the cat fits between it and the top of the screen."""
    monitor = monitor_of(rect, monitors) if monitors else None
    if monitor is None or rect.top - monitor.rect.top < need:
        return None
    if rect.top >= monitor.work.bottom:
        return None
    left, right = _span(rect.left, rect.right, margin)
    return Seat("window", hwnd, rect.top, left, right)


def seat_for(win, monitors: list, need: int, margin: int):
    """Where the cat sits to keep you company in `win`: on its top edge, or on the
    taskbar below it when the window reaches the top of the screen (maximised)."""
    if not monitors or win is None:
        return None
    seat = window_seat(win.hwnd, win.rect, monitors, need, margin)
    if seat:
        return seat
    monitor = monitor_of(win.rect, monitors)
    return floor_seat(monitor, margin, (win.rect.left, win.rect.right))


def uncovered(above: list, y: int, span: tuple) -> list:
    """The pieces of row `y` from span[0] to span[1] that no window in `above` hides."""
    open_ = [span] if span[1] > span[0] else []
    for rect in above:
        if not rect.top <= y < rect.bottom:
            continue
        cut: list = []
        for lo, hi in open_:
            if rect.right <= lo or rect.left >= hi:
                cut.append((lo, hi))
                continue
            if rect.left > lo:
                cut.append((lo, rect.left))
            if rect.right < hi:
                cut.append((rect.right, hi))
        open_ = cut
    return open_


def drop_seat(x: int, feet: int, wins: list, monitors: list, need: int, margin: int, slack: int = 24) -> Seat:
    """Where a cat let go at (x, feet) lands: the first window edge below it that is not
    hidden by a window above, else the taskbar of that monitor."""
    best = None
    for i, win in enumerate(wins):
        if not win.perch or win.rect.top < feet - slack:
            continue
        seat = window_seat(win.hwnd, win.rect, monitors, need, margin)
        if seat is None or not win.rect.left <= x < win.rect.right:
            continue
        free = uncovered([w.rect for w in wins[:i]], win.rect.top, (win.rect.left, win.rect.right))
        if not any(lo <= x < hi for lo, hi in free):
            continue
        if best is None or seat.y < best.y:
            best = seat
    monitor = monitor_at(x, feet, monitors)
    floor = floor_seat(monitor, margin)
    if best is not None and best.y <= floor.y:
        return best
    return floor
