"""Tests for everything that does not need a screen: geometry, learning, tasks, the timer.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workcat import apps, brain, media, sprites, tasks, world  # noqa: E402
from workcat.focus import Focus  # noqa: E402
from workcat.scene import Scene, look_of, rest_anim  # noqa: E402
from workcat.store import Store  # noqa: E402
from workcat.tracker import Tracker, day_of, slot_label, slot_of  # noqa: E402

Rect = namedtuple("Rect", "left top right bottom")
Monitor = namedtuple("Monitor", "rect work primary")
Win = namedtuple("Win", "hwnd rect pid cls perch")


class RectC(Rect):
    def contains(self, x, y):
        return self.left <= x < self.right and self.top <= y < self.bottom


def monitor(left=0, top=0, width=1920, height=1080, bar=48, primary=True):
    return Monitor(RectC(left, top, left + width, top + height), RectC(left, top, left + width, top + height - bar), primary)


def window(hwnd, left, top, right, bottom, perch=True):
    return Win(hwnd, RectC(left, top, right, bottom), 1, "App", perch)


NEED, MARGIN = 78, 60


class WorldTest(unittest.TestCase):
    def setUp(self):
        self.monitors = [monitor(), monitor(left=1920, primary=False)]

    def test_sits_on_a_window_with_room_above(self):
        seat = world.seat_for(window(7, 300, 200, 1100, 800), self.monitors, NEED, MARGIN)
        self.assertEqual((seat.kind, seat.hwnd, seat.y, seat.left, seat.right), ("window", 7, 200, 360, 1040))

    def test_maximised_window_sends_the_cat_to_the_taskbar_below_it(self):
        seat = world.seat_for(window(7, 1920, 0, 3840, 1032), self.monitors, NEED, MARGIN)
        self.assertEqual((seat.kind, seat.hwnd, seat.y), ("floor", 0, 1032))
        self.assertTrue(1920 < seat.left < seat.right < 3840)

    def test_window_too_close_to_the_top_has_no_room(self):
        self.assertIsNone(world.window_seat(7, RectC(100, 40, 900, 600), self.monitors, NEED, MARGIN))
        self.assertIsNotNone(world.window_seat(7, RectC(100, 78, 900, 600), self.monitors, NEED, MARGIN))

    def test_half_width_window_narrows_the_floor(self):
        seat = world.seat_for(window(7, 0, 0, 960, 1032), self.monitors, NEED, MARGIN)
        self.assertEqual((seat.kind, seat.left, seat.right), ("floor", 60, 900))

    def test_narrow_window_shrinks_to_its_middle(self):
        seat = world.window_seat(7, RectC(500, 300, 600, 700), self.monitors, NEED, MARGIN)
        self.assertEqual((seat.left, seat.right), (550, 550))

    def test_clamp(self):
        seat = world.Seat("window", 1, 100, 200, 400)
        self.assertEqual([seat.clamp(x) for x in (0, 300, 999)], [200, 300, 400])

    def test_uncovered(self):
        above = [RectC(100, 0, 200, 500), RectC(350, 90, 400, 110), RectC(0, 300, 999, 400)]
        self.assertEqual(world.uncovered(above, 100, (0, 500)), [(0, 100), (200, 350), (400, 500)])
        self.assertEqual(world.uncovered(above, 600, (0, 500)), [(0, 500)])

    def test_drop_lands_on_the_first_edge_below(self):
        wins = [window(1, 200, 500, 900, 900), window(2, 100, 300, 1000, 950)]
        self.assertEqual(world.drop_seat(600, 250, wins, self.monitors, NEED, MARGIN).hwnd, 2)
        self.assertEqual(world.drop_seat(600, 400, wins, self.monitors, NEED, MARGIN).hwnd, 1)

    def test_drop_skips_an_edge_hidden_by_a_window_on_top(self):
        wins = [window(1, 500, 100, 800, 900), window(2, 100, 300, 1000, 950)]
        self.assertEqual(world.drop_seat(600, 250, wins, self.monitors, NEED, MARGIN).kind, "floor")
        self.assertEqual(world.drop_seat(300, 250, wins, self.monitors, NEED, MARGIN).hwnd, 2)

    def test_drop_beside_every_window_lands_on_that_monitors_taskbar(self):
        seat = world.drop_seat(2500, 250, [window(1, 200, 500, 900, 900)], self.monitors, NEED, MARGIN)
        self.assertEqual((seat.kind, seat.y), ("floor", 1032))
        self.assertTrue(seat.left > 1920)

    def test_monitor_at_falls_back_to_the_nearest(self):
        self.assertIs(world.monitor_at(5000, 500, self.monitors), self.monitors[1])
        self.assertIs(world.monitor_at(-50, 500, self.monitors), self.monitors[0])


def days_back(today: dt.date, count: int) -> list:
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(1, count + 1)]


class BrainTest(unittest.TestCase):
    TODAY = "2026-11-12"  # a Thursday

    def usage(self):
        """Two weeks in which Excel is opened around 09:30 and mail around 14:00 on workdays."""
        usage = {}
        for i, day in enumerate(days_back(dt.date.fromisoformat(self.TODAY), 14)):
            if brain.is_weekend(day):
                usage[day] = {"vlc": {80: 900, 81: 900, 82: 900}}
                continue
            start = 38 + (i % 3) - 1  # 09:15, 09:30 or 09:45
            usage[day] = {
                "chrome": {slot: 600 for slot in range(36, 70)},
                "excel": {start: 700, start + 1: 800, start + 2: 500},
                "outlook": {56: 400, 57: 300},
            }
            if i % 4 == 0:
                usage[day]["blender"] = {60: 900, 61: 900}
        return usage

    def test_comparable_days_are_recent_days_of_the_same_kind(self):
        days = brain.comparable_days(self.usage(), self.TODAY)
        self.assertEqual(len(days), 10)
        self.assertTrue(all(not brain.is_weekend(day) and day < self.TODAY for day in days))
        self.assertEqual(days, sorted(days, reverse=True))
        self.assertEqual(len(brain.comparable_days(self.usage(), "2026-11-14")), 4)  # a Saturday

    def test_a_day_barely_used_does_not_count(self):
        usage = self.usage()
        usage["2026-11-11"] = {"chrome": {40: 200}}
        self.assertNotIn("2026-11-11", brain.comparable_days(usage, self.TODAY))

    def test_session_starts_need_an_hour_without_it(self):
        self.assertEqual(brain.session_starts({38: 700, 39: 800, 40: 500}), [38])
        self.assertEqual(brain.session_starts({38: 700, 39: 800, 50: 600, 51: 600}), [38, 50])
        self.assertEqual(brain.session_starts({38: 100, 39: 100}), [])

    def test_routines_found(self):
        usage = self.usage()
        found = {r.place: r for r in brain.find_routines(usage, brain.comparable_days(usage, self.TODAY))}
        self.assertIn("excel", found)
        self.assertIn(found["excel"].slot, (37, 38, 39))
        self.assertEqual(found["excel"].seen, 10)
        self.assertEqual(found["outlook"].slot, 56)
        self.assertNotIn("blender", found)  # only now and then
        self.assertEqual(found["chrome"].slot, 36)  # started once a day, then never put down

    def test_skip_and_too_few_days(self):
        usage = self.usage()
        days = brain.comparable_days(usage, self.TODAY)
        self.assertNotIn("chrome", {r.place for r in brain.find_routines(usage, days, skip={"chrome"})})
        self.assertEqual(brain.find_routines(usage, days[:2]), [])

    def test_due_routines(self):
        routines = [brain.Routine("excel", 38, 9, 10), brain.Routine("outlook", 56, 7, 10)]
        at = lambda minute, recent=(): [r.place for r in brain.due_routines(routines, minute, set(recent))]
        self.assertEqual(at(9 * 60 + 30), ["excel"])
        self.assertEqual(at(9 * 60 + 24), [])
        self.assertEqual(at(10 * 60), ["excel"])
        self.assertEqual(at(10 * 60 + 1), [])
        self.assertEqual(at(9 * 60 + 30, recent=["excel"]), [])
        self.assertEqual(at(14 * 60 + 10), ["outlook"])

    def test_typical_hours(self):
        usage = self.usage()
        self.assertEqual(brain.typical_hours(usage, brain.comparable_days(usage, self.TODAY)), (36, 70))
        self.assertIsNone(brain.typical_hours(usage, []))

    def plays(self, now: float) -> list:
        out = []
        for back in range(1, 9):
            evening = dt.datetime.fromtimestamp(now).replace(hour=21, minute=5, second=0) - dt.timedelta(days=back)
            start = int(evening.timestamp())
            out.append(dict(started=start, ended=start + 1500, app="Spotify.exe", title=f"Song {back}", artist="Lo-Fi Cat", kind="music"))
            if back % 3 == 0:
                out.append(dict(started=start + 1600, ended=start + 1900, app="chrome", title="Clip", artist="Some Channel", kind="web"))
        morning = int((dt.datetime.fromtimestamp(now).replace(hour=8, minute=0, second=0) - dt.timedelta(days=1)).timestamp())
        out.append(dict(started=morning, ended=morning + 4000, app="chrome", title="News", artist="Morning Show", kind="web"))
        return out

    def test_listening_habits(self):
        now = dt.datetime(2026, 11, 12, 21, 0).timestamp()
        plays = self.plays(now)
        days = days_back(dt.date(2026, 11, 12), 8)
        self.assertEqual(brain.listening_days(plays, days, 21), 8)
        self.assertEqual(brain.listening_days(plays, days, 15), 0)
        self.assertEqual(brain.favourite(plays, now, hour=21)["who"], "Lo-Fi Cat")
        self.assertEqual(brain.favourite(plays, now, hour=8)["who"], "Morning Show")
        self.assertIsNone(brain.favourite(plays, now, hour=3))
        self.assertEqual(brain.favourite(plays, now)["who"], "Lo-Fi Cat")

    def test_on_repeat(self):
        now = dt.datetime(2026, 11, 12, 21, 0).timestamp()
        pick = brain.on_repeat(self.plays(now), now)
        self.assertEqual((pick["who"], pick["plays"]), ("Lo-Fi Cat", 7))
        self.assertIsNone(brain.on_repeat(self.plays(now)[:3], now))

    def test_during(self):
        plays = [dict(started=100), dict(started=500), dict(started=900)]
        self.assertEqual(brain.during(plays, [(0, 200), (800, 1000)]), [plays[0], plays[2]])

    def test_music_that_goes_with_a_place(self):
        now = dt.datetime(2026, 11, 12, 21, 0).timestamp()
        plays, usage = [], {}
        for back in range(1, 5):
            when = dt.datetime(2026, 11, 12, 10, 2) - dt.timedelta(days=back)
            start = int(when.timestamp())
            plays.append(dict(started=start, ended=start + 1200, app="Spotify.exe", title="Beat", artist="Lo-Fi Cat", kind="music"))
            plays.append(dict(started=start + 5 * 3600, ended=start + 5 * 3600 + 900, app="chrome", title="Show", artist="Some Channel", kind="web"))
            usage[when.strftime("%Y-%m-%d")] = {"code": {40: 800, 41: 700}, "chrome": {60: 900}}
        self.assertEqual(brain.place_music(plays, usage, "code", now)["who"], "Lo-Fi Cat")
        self.assertEqual(brain.place_music(plays, usage, "chrome", now)["who"], "Some Channel")
        self.assertIsNone(brain.place_music(plays, usage, "excel", now))
        self.assertIsNone(brain.place_music(plays[:4], usage, "code", now))  # two days are not a habit yet


class TasksTest(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 12, 14, 0)

    def parse(self, text):
        what, when = tasks.parse_quick(text, self.NOW)
        return what, when and when.strftime("%m-%d %H:%M")

    def test_times(self):
        self.assertEqual(self.parse("Call the bank at 15:30"), ("Call the bank", "11-12 15:30"))
        self.assertEqual(self.parse("Call the bank 9:15"), ("Call the bank", "11-13 09:15"))  # already past today
        self.assertEqual(self.parse("Stretch in 20 min"), ("Stretch", "11-12 14:20"))
        self.assertEqual(self.parse("Review in 2 hours"), ("Review", "11-12 16:00"))
        self.assertEqual(self.parse("Send report tomorrow 9:00"), ("Send report", "11-13 09:00"))
        self.assertEqual(self.parse("Send report tomorrow"), ("Send report", "11-13 09:00"))
        self.assertEqual(self.parse("Stand-up at 5pm"), ("Stand-up", "11-12 17:00"))
        self.assertEqual(self.parse("Lunch at 12.30"), ("Lunch", "11-13 12:30"))

    def test_not_times(self):
        self.assertEqual(self.parse("Water the plants"), ("Water the plants", None))
        self.assertEqual(self.parse("Install version 3.10"), ("Install version 3.10", None))
        self.assertEqual(self.parse("Buy 2 apples"), ("Buy 2 apples", None))
        self.assertEqual(self.parse("Meeting at 25:99"), ("Meeting at 25:99", None))

    def test_due_and_retry(self):
        base = dict(done=None, place=None, repeat=0, shown=None, tries=0)
        late = dict(base, id=1, due=1000)
        later = dict(base, id=2, due=5000)
        done = dict(base, id=3, due=1000, done=1500)
        shown = dict(base, id=4, due=1000, shown=1900, tries=1)
        gave_up = dict(base, id=5, due=1000, shown=100, tries=tasks.MAX_TRIES)
        note = dict(base, id=6, due=None, place="excel")
        ids = lambda now: [t["id"] for t in tasks.due_tasks([late, later, done, shown, gave_up, note], now)]
        self.assertEqual(ids(2000), [1])
        self.assertEqual(ids(1900 + tasks.RETRY_AFTER), [1, 4])
        self.assertEqual(ids(6000 + tasks.RETRY_AFTER), [1, 2, 4])

    def test_notes_for_a_place(self):
        base = dict(done=None, due=None, tries=0)
        once = dict(base, id=1, place="excel", repeat=0, shown=None)
        every = dict(base, id=2, place="excel", repeat=1, shown=1000)
        other = dict(base, id=3, place="word", repeat=0, shown=None)
        ids = lambda now: [t["id"] for t in tasks.notes_for([once, every, other], "excel", now)]
        self.assertEqual(ids(1000 + 600), [1])
        self.assertEqual(ids(1000 + tasks.NOTE_GAP), [1, 2])

    def test_labels(self):
        stamp = lambda *a: int(dt.datetime(*a).timestamp())
        self.assertEqual(tasks.due_label(stamp(2026, 11, 12, 15, 30), self.NOW), "15:30")
        self.assertEqual(tasks.due_label(stamp(2026, 11, 13, 9, 0), self.NOW), "tomorrow 09:00")
        self.assertEqual(tasks.due_label(stamp(2026, 11, 12, 9, 0), self.NOW), "late")
        self.assertEqual(tasks.due_label(None, self.NOW), "")


class FocusTest(unittest.TestCase):
    def test_cycle(self):
        f = Focus()
        self.assertIsNone(f.tick(0))
        f.start(1000, 25)
        self.assertTrue(f.focusing)
        self.assertEqual(f.minutes_left(1000), 25)
        self.assertEqual(f.minutes_left(1000 + 24 * 60 + 59), 1)
        self.assertAlmostEqual(f.progress(1000 + 750), 0.5)
        self.assertIsNone(f.tick(2499))
        self.assertEqual(f.tick(2500), "focus_done")
        self.assertIsNone(f.phase)
        self.assertIsNone(f.tick(2600))
        f.start_break(3000, 5)
        self.assertTrue(f.on_break)
        self.assertEqual(f.tick(3300), "break_done")
        self.assertEqual(f.progress(3300), 0.0)


class SceneTest(unittest.TestCase):
    def test_what_the_cat_does(self):
        self.assertEqual(rest_anim(Scene("code")), "work")
        self.assertEqual(rest_anim(Scene("code", idle=90)), "sit")
        self.assertEqual(rest_anim(Scene("code", idle=400)), "sleep")
        self.assertEqual(rest_anim(Scene("code", idle=400, focus=0.5)), "focus")
        self.assertEqual(rest_anim(Scene("browser", music=True)), "listen")
        self.assertEqual(rest_anim(Scene("comms", music=True, in_call=True)), "sit")
        self.assertEqual(rest_anim(Scene("other")), "sit")

    def test_what_the_cat_wears(self):
        self.assertEqual(look_of(Scene("code")), look_of(Scene("code")))
        self.assertEqual((look_of(Scene("code")).acc, look_of(Scene("code")).item), ("glasses", "laptop"))
        self.assertTrue(look_of(Scene("office")).tie)
        self.assertEqual(look_of(Scene("design")).item, "easel")
        self.assertEqual(look_of(Scene("code", in_call=True)).acc, "headset")
        self.assertEqual(look_of(Scene("browser", music=True)).acc, "headphones")
        self.assertEqual(look_of(Scene("code", music=True)).acc, "glasses")
        self.assertEqual(look_of(Scene("browser", focus=0.2)).item, "laptop")
        self.assertIsNone(look_of(Scene("browser")).item)


class AppsTest(unittest.TestCase):
    def site(self, title):
        found = apps.site_of_title(title)
        return found and found.name

    def test_sites_from_tab_titles(self):
        self.assertEqual(self.site("Some video - YouTube - Google Chrome"), "YouTube")
        self.assertEqual(self.site("(3) Inbox - someone@example.com - Gmail - Google Chrome"), "Gmail")
        self.assertEqual(self.site("Budget \u2013 Google Sheets \u2014 Mozilla Firefox"), "Google Sheets")
        self.assertEqual(self.site("GitHub - owner/repo: a description - Brave"), "GitHub")
        self.assertEqual(self.site("Home / X - Google Chrome"), "X")
        self.assertEqual(self.site("Feed | LinkedIn - Personal - Microsoft\u200b Edge"), "LinkedIn")
        self.assertEqual(self.site("Song - YouTube Music - Google Chrome"), "YouTube Music")
        self.assertEqual(self.site("Video - YouTube and 5 more pages - Personal - Microsoft\u200b Edge"), "YouTube")
        self.assertEqual(self.site("(2) WhatsApp - Google Chrome"), "WhatsApp")

    def test_a_page_that_only_mentions_a_site_is_not_that_site(self):
        self.assertEqual(self.site("How to embed YouTube videos - Stack Overflow - Google Chrome"), "Stack Overflow")
        self.assertIsNone(self.site("Why I left GitHub and Gmail behind - My Blog - Google Chrome"))
        self.assertIsNone(self.site("New Tab - Google Chrome"))
        self.assertIsNone(self.site(""))

    def test_identify(self):
        place = apps.identify(r"C:\Program Files\Microsoft Office\EXCEL.EXE", "Microsoft Excel")
        self.assertEqual((place.id, place.name, place.category), ("excel", "Excel", "office"))
        place = apps.identify(r"C:\Apps\chrome.exe", "Google Chrome", "Video - YouTube - Google Chrome")
        self.assertEqual((place.id, place.name, place.category, place.url), ("site:youtube", "YouTube", "media", "https://www.youtube.com"))
        self.assertEqual(apps.identify(r"C:\Apps\chrome.exe", "Google Chrome").id, "chrome")
        self.assertEqual(apps.identify(r"C:\Apps\chrome.exe", "Google Chrome", "My bank - Google Chrome").id, "chrome")
        place = apps.identify(r"C:\Apps\EXCEL.EXE", "Microsoft Excel", "YouTube - notes.xlsx")  # titles count for browsers only
        self.assertEqual(place.id, "excel")

    def test_names_and_kinds(self):
        self.assertEqual(apps.category_of("telegram_2"), "comms")
        self.assertEqual(apps.category_of("gimp-2.10"), "design")
        self.assertEqual(apps.category_of("docker desktop"), "code")
        self.assertEqual(apps.category_of("somethingelse"), "other")
        self.assertEqual(apps.pretty_name("my-cool_app", "Electron"), "My Cool App")
        self.assertEqual(apps.pretty_name("foo", "Foo Studio"), "Foo Studio")
        self.assertEqual(apps.pretty_name("telegram_2", "Telegram Desktop"), "Telegram")
        self.assertIn("chrome", apps.BROWSERS)
        self.assertEqual(set(apps.EXE_CATEGORY.values()) - set(apps.CATEGORY_NAMES), set())


class SpritesTest(unittest.TestCase):
    def test_parts_are_rectangles(self):
        sprites.check_parts()

    def test_every_animation_gives_full_frames_in_known_colours(self):
        keys = set(sprites.palette()) | {sprites.EMPTY}
        looks = [(None, None, False), ("glasses", "laptop", False), ("beret", "easel", False), ("gradcap", "book", True), ("headset", None, True), ("headphones", None, False)]
        for anim in sprites.ANIMS:
            for t in range(0, 5000, 130):
                for acc, item, tie in looks:
                    rows = sprites.frame(anim, t, acc, item, tie, progress=(t % 1000) / 1000)
                    self.assertEqual(len(rows), sprites.SIZE, anim)
                    self.assertTrue(all(len(row) == sprites.SIZE for row in rows), anim)
                    self.assertLessEqual(set("".join(rows)), keys, anim)

    def test_the_cat_stands_on_the_bottom_row(self):
        for anim in ("sit", "work", "walk", "sleep", "talk"):
            self.assertNotEqual(set(sprites.frame(anim, 500)[-1]), {sprites.EMPTY}, anim)

    def test_mirror_and_rim(self):
        rows = sprites.frame("walk", 0)
        self.assertEqual(sprites.mirror(sprites.mirror(rows)), rows)
        rimmed = sprites.rimmed(rows)
        for before, after in zip(rows, rimmed):
            for a, b in zip(before, after):
                self.assertTrue(a == b or (a == sprites.EMPTY and b == sprites.RIM))
        self.assertIn(sprites.RIM, "".join(rimmed))

    def test_icon(self):
        for size in (16, 32, 48):
            rows = sprites.icon_rows(size)
            self.assertEqual((len(rows), len(rows[0])), (size, size))

    def test_every_coat_has_every_colour(self):
        for coat in sprites.COAT_NAMES:
            self.assertEqual(set(sprites.COATS[coat]), set("ofdsxymwvpcekhl"), coat)

    def test_every_mood_can_be_drawn_and_shows(self):
        calm = sprites.frame("sit", 2000, mood="content")
        for name in sprites.MOOD_NAMES:
            for t in range(0, 22000, 700):
                rows = sprites.frame("sit", t, mood=name)
                self.assertEqual((len(rows), len(rows[0])), (sprites.SIZE, sprites.SIZE), name)
        for name in ("sleepy", "tired", "worried", "lonely", "focused"):
            self.assertNotEqual(sprites.frame("sit", 2000, mood=name), calm, name)  # you can see it in the face
        self.assertEqual(sprites.frame("sit", 2000, mood="no such mood"), calm)

    def test_the_paws_do_not_slide(self):
        # a paw on the ground moves back exactly as fast as the cat moves forward
        cycle = 8 * sprites.WALK_STEP_MS / 1000
        self.assertAlmostEqual(sprites.WALK_SPEED * cycle / 2, 2 * sprites.WALK_STRIDE)
        self.assertEqual(len({sprites.frame("walk", i * sprites.WALK_STEP_MS) for i in range(8)}), 8)

    def test_portrait_and_measures(self):
        face = sprites.face_rows()
        self.assertTrue(all(len(row) == len(face[0]) for row in face))
        self.assertTrue(8 <= sprites.SIT_TOP <= 14)
        self.assertEqual(sprites.first_row(sprites.frame("sit", 2000)), sprites.SIT_TOP)


class MoodTest(unittest.TestCase):
    def feel(self, **facts):
        from workcat import mood

        return mood.condition(mood.Day(**{"hour": 10.5, **facts}))

    def test_moods_follow_the_day(self):
        self.assertEqual(self.feel().mood, "content")
        self.assertEqual(self.feel(focusing=True).mood, "focused")
        self.assertEqual(self.feel(idle_s=900).mood, "sleepy")
        self.assertEqual(self.feel(since_pet=30, pets=1).mood, "happy")
        self.assertEqual(self.feel(since_win=120).mood, "proud")
        self.assertEqual(self.feel(hour=23.5).mood, "sleepy")
        self.assertEqual(self.feel(streak_s=95 * 60).mood, "worried")
        self.assertEqual(self.feel(active_s=9.5 * 3600).mood, "tired")
        self.assertEqual(self.feel(hour=20.0, usual_end=18.0, active_s=5 * 3600).mood, "tired")
        self.assertEqual(self.feel(tasks_late=1).mood, "worried")
        self.assertEqual(self.feel(on_break=True).mood, "playful")
        self.assertEqual(self.feel(focus_count=3).mood, "proud")
        self.assertEqual(self.feel(music=True).mood, "cozy")
        self.assertEqual(self.feel(hour=15.0, active_s=4 * 3600, pets=0).mood, "lonely")
        self.assertEqual(self.feel(hour=15.0, active_s=4 * 3600, pets=1).mood, "content")
        self.assertEqual(self.feel(hour=9.0, since_start=600).mood, "fresh")
        self.assertEqual(self.feel(weekend=True).mood, "playful")
        self.assertEqual(self.feel(breaks=2).mood, "happy")

    def test_every_mood_has_a_face_and_a_word(self):
        from workcat import mood

        seen = {self.feel(**facts).mood for facts in (
            {}, {"focusing": True}, {"idle_s": 900}, {"since_pet": 5}, {"since_win": 5}, {"streak_s": 6000}, {"active_s": 40000},
            {"on_break": True}, {"music": True}, {"hour": 15.0, "active_s": 14400}, {"hour": 9.0, "since_start": 60},
        )}
        self.assertEqual(seen, set(sprites.MOOD_NAMES))
        self.assertEqual(set(mood.MOOD_WORDS), set(sprites.MOOD_NAMES))
        self.assertTrue(all(self.feel(**f).why for f in ({}, {"streak_s": 6000}, {"focus_count": 4})))

    def test_energy_follows_the_clock_and_the_work(self):
        from workcat import mood

        level = lambda **facts: mood.energy(mood.Day(**{"hour": 10.0, **facts}))
        self.assertGreater(level(), 90)
        self.assertLess(level(hour=23.5), 30)
        self.assertLess(level(hour=3.0), 30)
        self.assertLess(level(streak_s=90 * 60), level() - 20)  # a long stretch drains it
        self.assertLess(level(active_s=10 * 3600), level() - 15)  # so does a long day
        self.assertGreater(level(hour=16.0, breaks=3), level(hour=16.0))  # pauses give some back
        self.assertTrue(all(5 <= level(hour=h, streak_s=9000, active_s=50000) <= 100 for h in range(24)))
        self.assertEqual([mood.energy_word(v) for v in (90, 60, 40, 10)], ["full of energy", "doing fine", "getting tired", "running low"])

    def test_bond_only_grows_in_steps(self):
        from workcat import mood

        self.assertEqual([mood.bond_level(p) for p in (0, 14, 15, 49, 50, 500, 9999)], [0, 0, 1, 1, 2, 5, 5])
        self.assertEqual(mood.bond_name(0), "New friends")
        self.assertEqual(mood.bond_progress(9999), 1.0)
        self.assertAlmostEqual(mood.bond_progress(32), (32 - 15) / 35)


class AdvisorTest(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 12, 15, 0).timestamp()

    def ideas(self, **facts):
        from workcat import advisor

        return advisor.ideas(advisor.Facts(now=self.NOW, **facts))

    def test_nothing_to_do_is_still_an_answer(self):
        found = self.ideas()
        self.assertEqual([idea.key for idea in found], ["none"])
        self.assertFalse(found[0].action)

    def test_what_matters_most_comes_first(self):
        task = lambda text, due=None, place=None: dict(text=text, due=due, place=place)
        found = self.ideas(
            tasks=(task("Send report", self.NOW - 600), task("Call bank", self.NOW + 1200), task("Read book"), task("Backup", place="excel")),
            streak_s=70 * 60, break_after_s=50 * 60, category="code", focus_count=0, active_s=3 * 3600,
            routines=(("excel", "Excel", 60),), next_place=("winword", "Word"), place_name="VS Code",
        )
        self.assertEqual([idea.key for idea in found], ["task", "break", "routine:excel"])
        self.assertIn("was due at 14:50", found[0].text)
        self.assertEqual(found[1].action, ("break",))
        self.assertEqual(found[2].action, ("open", "excel"))

    def test_each_kind_of_idea(self):
        task = lambda text, due=None: dict(text=text, due=due, place=None)
        keys = lambda **facts: [idea.key for idea in self.ideas(**facts)]
        self.assertEqual(keys(tasks=(task("Later", self.NOW + 7200),)), ["none"])  # not due soon: no nagging
        self.assertEqual(keys(tasks=(task("Read book"),)), ["list"])
        self.assertEqual(keys(category="code", active_s=3600), ["focus"])
        self.assertEqual(keys(category="code", active_s=3600, focusing=True), ["none"])
        self.assertEqual(keys(category="browser", active_s=3600), ["none"])
        self.assertEqual(keys(next_place=("excel", "Excel"), place_name="Gmail"), ["next:excel"])
        self.assertEqual(keys(usual_end=14.0, active_s=4 * 3600), ["wrap"])
        self.assertEqual(keys(energy=20), ["energy"])
        self.assertEqual(keys(streak_s=4000, break_after_s=0), ["none"])  # break reminders are switched off
        self.assertEqual(keys(music={"who": "Lo-Fi Cat"}, place_name="VS Code"), ["music"])


class AssistantTest(unittest.TestCase):
    def test_reply_is_read_while_it_is_written(self):
        from workcat import assistant

        reader = assistant.ReplyReader()
        answer = '{"reply": "Sure! \\"Call\\" set.\\nAnything else? \\u00e9", "reminders": [], "focus_minutes": 0, "start_break": true, "suggestions": []}'
        said = "".join(reader.feed(answer[i:i + 3]) for i in range(0, len(answer), 3))
        self.assertEqual(said, 'Sure! "Call" set.\nAnything else? é')
        self.assertTrue(reader.done)
        self.assertEqual(reader.text, said)
        for size in (1, 2, 5, 7, 50):  # however the answer is cut into pieces, the words are the same
            again = assistant.ReplyReader()
            self.assertEqual("".join(again.feed(answer[i:i + size]) for i in range(0, len(answer), size)), said)

    def test_answers_are_checked_before_anything_is_done(self):
        import json

        from workcat import assistant

        answer = dict(
            reply=" Done.  Actions: ",
            reminders=[{"text": " call  Aziz ", "when": "tomorrow 09:00"}, {"text": "", "when": "10:00"}, "junk", {"text": "Buy milk"}],
            focus_minutes=25,
            start_break=True,
            suggestions=["A - B", "", "Artist - Title", "A - B", "C", "D", "E"],
            delete_files=True,
        )
        reply, actions = assistant.parse(json.dumps(answer))
        self.assertEqual(reply, "Done.")
        self.assertEqual(actions, [
            {"do": "remind", "text": "Call Aziz", "when": "tomorrow 09:00"},
            {"do": "remind", "text": "Buy milk", "when": ""},
            {"do": "focus", "minutes": 25},  # a focus round and a break at once: the focus wins
            {"do": "suggest", "items": ["A - B", "C", "D"]},  # no blanks, no placeholders, no repeats, three at most
        ])
        only = lambda **fields: assistant.parse(json.dumps({"reply": "ok", **fields}))[1]
        self.assertEqual(only(focus_minutes=9999), [])
        self.assertEqual(only(focus_minutes="soon"), [])
        self.assertEqual(only(start_break=True), [{"do": "break"}])
        self.assertEqual(only(start_break="yes"), [])
        self.assertEqual(only(reminders=[{"text": f"Thing {i}", "when": ""} for i in range(9)])[3:], [])  # three reminders at most

    def test_a_broken_answer_becomes_plain_words(self):
        from workcat import assistant

        self.assertEqual(assistant.parse('{"reply": "Half an ans'), ("Half an ans", []))
        self.assertEqual(assistant.parse("just words"), ("just words", []))
        self.assertEqual(assistant.parse('["a list"]'), ("['a list']", []))
        self.assertEqual(assistant.parse('{"reply": "ok", "reminders": "none", "suggestions": 5}'), ("ok", []))
        self.assertEqual(assistant.tidy("Let's focus! {"), "Let's focus!")
        self.assertEqual(assistant.tidy("Sure. Actions:"), "Sure.")
        self.assertEqual(assistant.tidy("Here are my suggestions"), "Here are my")  # rare, and harmless
        self.assertEqual(assistant.tidy(""), "")

    def test_how_a_message_is_written(self):
        from workcat import assistant

        writing = assistant.writing
        self.assertEqual(writing("Remind me to call Aziz tomorrow at 9"), "en")
        self.assertEqual(writing("What should I do now?"), "en")
        self.assertEqual(writing("hi"), "en")
        self.assertEqual(writing("Remind me at 9 o'clock"), "en")  # o'clock is not Uzbek
        self.assertEqual(writing("I'm tired"), "en")
        self.assertEqual(writing("Привет! Как проходит мой день?"), "ru")
        self.assertEqual(writing("Напомни про Excel завтра"), "ru")  # one English word in a Russian sentence
        self.assertEqual(writing("Открой Excel"), "ru")
        self.assertEqual(writing("Voy a casa mañana, no me esperes"), "latn")
        self.assertEqual(writing("Un po' di musica per favore"), "latn")  # Italian has an o' too
        self.assertEqual(writing("你好，今天怎么样？"), "other")
        self.assertEqual(writing("Привіт, як справи?"), "xx-cyrl")  # Ukrainian: neither Russian nor Uzbek
        self.assertEqual(writing("Сәлем, қалайсың?"), "xx-cyrl")  # Kazakh shares қ with Uzbek
        self.assertEqual(writing("Музей"), "cyrl")  # Cyrillic, but one word does not say which language
        self.assertEqual(writing("ok"), "")  # too little to tell
        self.assertEqual(writing("15:30?"), "")
        self.assertEqual(writing(""), "")

    def test_uzbek_is_told_apart_by_its_alphabet(self):
        from workcat import assistant

        writing = assistant.writing
        self.assertEqual(writing("Салом! Эртага соат 10 да ҳисобот юборишни эслатиб қўй"), "uz-cyrl")
        self.assertEqual(writing("Куним қандай ўтяпти?"), "uz-cyrl")
        self.assertEqual(writing("Бугун нима бор?"), "uz-cyrl")  # none of ў қ ғ ҳ, known by its words
        self.assertEqual(writing("Майли"), "uz-cyrl")
        self.assertEqual(writing("Excel ва YouTube очиш керак"), "uz-cyrl")  # names in Latin letters do not make it Latin
        self.assertEqual(writing("Salom! Ertaga soat 10 da hisobot yuborishni eslatib qo'y"), "uz-latn")
        self.assertEqual(writing("Kunim qanday o‘tyapti?"), "uz-latn")
        self.assertEqual(writing("Bugun nima bor?"), "uz-latn")
        self.assertEqual(writing("rahmat"), "uz-latn")
        self.assertEqual(writing("To'g'ri, rahmat"), "uz-latn")  # the "to" in to'g'ri is not English
        self.assertEqual(writing("Hisobot yuborishga e'tibor qiling!"), "uz-latn")  # a q without u
        self.assertEqual(writing("Tog' havosi"), "uz-latn")

    def test_which_way_to_answer_when_the_message_does_not_say(self):
        from workcat import assistant

        Talk = assistant.Talk
        # No words at all: the talk so far decides, and at its very start the app's own language.
        self.assertEqual(Talk().turn("15:30?", "uz").style, "uz-cyrl")
        self.assertEqual(Talk().turn("15:30?", "ru").style, "ru")
        self.assertEqual(Talk().turn("15:30?", "en").style, "")
        talk = Talk()
        self.assertEqual(talk.turn("Bugun nima bor?", "uz").style, "uz-latn")  # words to go by: the app's language decides nothing
        self.assertEqual(talk.turn("ok", "uz").style, "uz-latn")  # carry on as before
        self.assertEqual(talk.turn("Kitob sotib olish", "uz").style, "uz-latn")
        self.assertEqual(talk.turn("15:30?", "uz").style, "uz-latn")
        # Cyrillic that could be either language.
        self.assertEqual(Talk().turn("Мактабга бориш", "uz").style, "uz-cyrl")
        self.assertEqual(Talk().turn("Мактабга бориш", "en").style, "cyrl")
        talk = Talk()
        self.assertEqual(talk.turn("Привет, как дела?", "uz").style, "ru")
        self.assertEqual(talk.turn("Музей", "uz").style, "ru")
        # A language that is plain to see is never overruled.
        self.assertEqual(Talk().turn("What should I do now?", "uz").style, "en")
        self.assertEqual(Talk().turn("Как дела?", "uz").style, "ru")
        talk = Talk()
        talk.turn("Салом, яхшимисиз?")
        self.assertEqual(talk.turn("How are you?").style, "en")
        self.assertEqual(talk.turn("Раҳмат!").style, "uz-cyrl")
        self.assertEqual(talk.turn("Привіт, як справи?").style, "xx-cyrl")  # plainly another language: not taken for Uzbek
        talk.clear()
        self.assertEqual(talk.turn("ok").style, "")

    def test_what_the_model_is_told_about_the_language(self):
        from workcat import assistant

        talk = assistant.Talk()
        self.assertEqual(talk.turn("What should I do now?").note, "(Answer in English.)")
        self.assertEqual(talk.turn("Как дела?").note, "(Answer in Russian.)")
        self.assertEqual(talk.turn("Bugun nima bor?").note, "(Answer in Uzbek, written in Latin letters like this message.)")
        self.assertEqual(talk.turn("Бугун нима бор?").note, "(Answer in Uzbek, written in Latin letters like this message.)")  # it is sent in Latin letters
        self.assertEqual(talk.turn("Привіт, як справи?").note, "(Answer in the language of this message and in its alphabet. Not in English.)")
        self.assertEqual(talk.turn("Voy a casa mañana, no me esperes").note, "(Answer in the same language as this message.)")
        self.assertEqual(talk.turn("你好，今天怎么样？").note, "(Answer in the language of this message, not in English.)")
        self.assertEqual(assistant.Talk().turn("15:30?").note, "(Answer in the language and alphabet the user has been using.)")

    def test_uzbek_in_cyrillic_goes_to_the_model_in_latin_letters_and_comes_back(self):
        from workcat import assistant

        talk = assistant.Talk()
        turn = talk.turn("Эртага соат 10 да ҳисобот юборишни эслатиб қўй")
        self.assertEqual(turn.style, "uz-cyrl")
        self.assertEqual(turn.text, "Эртага соат 10 да ҳисобот юборишни эслатиб қўй")
        self.assertEqual(turn.sent, "Ertaga soat 10 da hisobot yuborishni eslatib qo'y")
        sent = talk.messages("system", turn)
        self.assertEqual(sent[-1]["content"], "Ertaga soat 10 da hisobot yuborishni eslatib qo'y\n\n(Answer in Uzbek, written in Latin letters like this message.)")
        raw = (
            '{"reply": "Albatta, ertaga soat 10 da eslatib qo\'yaman!", "reminders": [{"text": "hisobot yuborish", "when": "tomorrow 10:00"}], '
            '"focus_minutes": 0, "start_break": false, "suggestions": ["Lo-Fi Girl"]}'
        )
        reply, actions = turn.result(raw)
        self.assertEqual(reply, "Албатта, эртага соат 10 да эслатиб қўяман!")
        self.assertEqual(actions[0], {"do": "remind", "text": "Ҳисобот юбориш", "when": "tomorrow 10:00"})
        self.assertEqual(actions[1], {"do": "suggest", "items": ["Lo-Fi Girl"]})  # what to look up is never respelled
        talk.add(turn, raw)
        self.assertEqual(talk.history[0], ("uz", {"role": "user", "content": turn.sent}))  # remembered the way the model saw it
        nxt = talk.messages("system", talk.turn("Раҳмат!"))
        self.assertEqual(nxt[1], {"role": "user", "content": turn.sent})  # earlier lines carry no note
        self.assertEqual(nxt[2], {"role": "assistant", "content": raw})
        self.assertTrue(nxt[-1]["content"].startswith("Rahmat!\n\n"))

    def test_the_model_is_shown_one_language_at_a_time(self):
        """After answers in one language a small model goes on in it whatever it is asked
        in. So a question in Russian travels with the Russian part of the talk only."""
        from workcat import assistant

        talk = assistant.Talk()
        for line in ("Салом!", "Bugun nima bor?", "Привет!", "Hello there, how are you?", "Раҳмат!"):
            talk.add(talk.turn(line), '{"reply": "..."}')

        def lines(text: str) -> list:
            return [m["content"] for m in talk.messages("system", talk.turn(text))[1:-1] if m["role"] == "user"]

        self.assertEqual(lines("Как дела?"), ["Привет!"])
        self.assertEqual(lines("What should I do now?"), ["Hello there, how are you?"])
        self.assertEqual(lines("Ҳозир нима қилай?"), ["Salom!", "Bugun nima bor?", "Rahmat!"])  # both alphabets are one language
        self.assertEqual(lines("Hozir nima qilay?"), ["Salom!", "Bugun nima bor?", "Rahmat!"])
        self.assertEqual(lines("ok"), ["Salom!", "Bugun nima bor?", "Rahmat!"])  # too short to tell: as the talk was going

    def test_slips_of_a_small_model_are_caught(self):
        from workcat import assistant

        both = '{"reply": "Try Lo-Fi Girl.", "reminders": [], "focus_minutes": 25, "start_break": false, "suggestions": ["Lo-Fi Girl"]}'
        for asked in ("Music for focusing?", "Музыка для концентрации?", "Диққатни жамлаш учун мусиқа?", "Diqqatni jamlash uchun musiqa tavsiya qil"):
            _, actions = assistant.Talk().turn(asked).result(both)
            self.assertEqual([a["do"] for a in actions], ["suggest"], asked)  # asking for music does not start a timer
        for asked in ("Start a focus session and suggest music", "Начни фокус и посоветуй музыку", "Фокусни бошла ва мусиқа тавсия қил", "Music for 25 minutes of focus"):
            _, actions = assistant.Talk().turn(asked).result(both)
            self.assertEqual([a["do"] for a in actions], ["focus", "suggest"], asked)
        alone = '{"reply": "Go!", "reminders": [], "focus_minutes": 25, "start_break": false, "suggestions": []}'
        self.assertEqual(assistant.Talk().turn("Let's focus").result(alone)[1], [{"do": "focus", "minutes": 25}])

        # A reminder that comes back in another language than the person's: their own words are used.
        english = '{"reply": "Xo\'p!", "reminders": [{"text": "Save the report", "when": ""}], "focus_minutes": 0, "start_break": false, "suggestions": []}'
        _, actions = assistant.Talk().turn("Excel'ни очганимда ҳисоботни сақлашни эслат").result(english)
        self.assertEqual(actions, [{"do": "remind", "text": "Excel'ни очганимда ҳисоботни сақлашни эслат", "when": ""}])
        _, actions = assistant.Talk().turn("Напомни сохранить отчёт").result(english)
        self.assertEqual(actions[0]["text"], "Напомни сохранить отчёт")
        _, actions = assistant.Talk().turn("Remind me to save the report").result(english)
        self.assertEqual(actions[0]["text"], "Save the report")  # the same language: the model's shorter wording stays
        two = '{"reply": "Ok", "reminders": [{"text": "Save the report", "when": ""}, {"text": "Buy some milk", "when": ""}]}'
        _, actions = assistant.Talk().turn("Ҳисоботни сақлаш ва сут олишни эслат").result(two)
        self.assertEqual([a["text"] for a in actions], ["Save the report", "Buy some milk"])  # two things cannot both be the whole message
        # Asked what to do, it "reminds" of a task that is on the list already, or of something
        # it thought of itself: a question is no wish to be reminded, so nothing is added ...
        again = '{"reply": "Send that report!", "reminders": [{"text": "Send the weekly report", "when": "today 17:00"}, {"text": "Stretch", "when": ""}]}'
        listed = ["Send the weekly report.", "Water the plants"]
        _, actions = assistant.Talk().turn("What should I do now?").result(again, listed)
        self.assertEqual(actions, [])
        uzbek = '{"reply": "Hisobotni yuboring!", "reminders": [{"text": "Send the weekly report", "when": "today 17:00"}, {"text": "suv ichish", "when": ""}]}'
        _, actions = assistant.Talk().turn("Ҳозир нима қилай?").result(uzbek, listed)
        self.assertEqual(actions, [])
        # ... and said without a question mark it is no such wish either. (Up to 0.7 a small
        # model's own idea, "Stretch", was then added to the list. The real Small model
        # showed what comes of that: see SmallModelTest in test_v7.)
        _, actions = assistant.Talk().turn("Tell me what to do now").result(again, listed)
        self.assertEqual(actions, [])
        _, actions = assistant.Talk().turn("Ҳозир нима қилишим кераклигини айт").result(uzbek, listed)
        self.assertEqual(actions, [])
        _, actions = assistant.Talk().turn("Tell me what to do now").result(again)
        self.assertEqual(actions, [])
        # A big model's own idea is still taken, only never what is on the list already.
        _, actions = assistant.Talk().turn("Tell me what to do now", careful=False).result(again, listed)
        self.assertEqual([a["text"] for a in actions], ["Stretch"])
        # And where a reminder is what was asked for, it is theirs to have.
        _, actions = assistant.Talk().turn("Remind me to send the weekly report at 5").result(again, listed)
        self.assertEqual([a["text"] for a in actions], ["Send the weekly report", "Stretch"])
        _, actions = assistant.Talk().turn("Ҳисоботни юборишни соат 5 да эслат").result(again, listed)
        self.assertEqual(len(actions), 2)

        mixed = '{"reply": "Xo\'p, eslataman!", "reminders": [{"text": "Check the weekly report", "when": ""}, {"text": "Sut olish", "when": ""}]}'
        reply, actions = assistant.Talk().turn("Ҳисоботни текшириш ва сут олишни эслат").result(mixed)
        self.assertEqual(reply, "Хўп, эслатаман!")
        self.assertEqual([a["text"] for a in actions], ["Check the weekly report", "Сут олиш"])  # each in its own letters

    def test_names_and_the_persons_own_words_survive_the_change_of_alphabet(self):
        from workcat import assistant, translit

        names = translit.latin_words("Lo-Fi Girl, Hans Zimmer, Excel, VS Code")
        turn = assistant.Talk().turn("Диққатни жамлаш учун мусиқа тавсия қил", keep=names)
        self.assertEqual(turn.shown("Lo-Fi Girl yoki Hans Zimmer tinglang. Excel'ni ham oching."), "Lo-Fi Girl ёки Hans Zimmer тингланг. Excel'ни ҳам очинг.")
        # A name the person writes in Cyrillic themselves is theirs to spell, whatever a task in English calls it.
        names = translit.latin_words("Call Aziz, Excel")
        turn = assistant.Talk().turn("Эртага Азизга қўнғироқ қилишни эслат", keep=names)
        self.assertEqual(turn.shown("Azizga qo'ng'iroq qilaman, Azizni Excelda topaman."), "Азизга қўнғироқ қиламан, Азизни Excelда топаман.")
        turn = assistant.Talk().turn("Эртага қўнғироқ қилишни эслат", keep=names)
        self.assertEqual(turn.shown("Azizga qo'ng'iroq qilaman."), "Azizга қўнғироқ қиламан.")  # not written by them: as the task has it
        turn = assistant.Talk().turn("Telegram'да Ильяга ёзишни эслат")  # a name typed in Latin letters, and one the rules would respell
        self.assertEqual(turn.sent, "Telegram'da Ilyaga yozishni eslat")
        reply, actions = turn.result('{"reply": "Xo\'p, Telegramda Ilyaga yozishni eslataman.", "reminders": [{"text": "Telegramda Ilyaga yozish", "when": ""}]}')
        self.assertEqual(reply, "Хўп, Telegramда Ильяга ёзишни эслатаман.")
        self.assertEqual(actions, [{"do": "remind", "text": "Telegramда Ильяга ёзиш", "when": ""}])

    def test_an_answer_in_the_wrong_alphabet_is_put_right(self):
        from workcat import assistant

        latin = assistant.Talk().turn("Rahmat, yaxshi!")
        self.assertEqual(latin.style, "uz-latn")
        self.assertEqual(latin.sent, "Rahmat, yaxshi!")
        self.assertEqual(latin.shown("Албатта! Бугун сизга ёрдам бераман."), "Albatta! Bugun sizga yordam beraman.")
        self.assertEqual(latin.shown("Sizga yana ishlashga тўғри келишини умид қиламан."), "Sizga yana ishlashga to'g'ri kelishini umid qilaman.")  # half and half
        self.assertEqual(latin.shown("Albatta, yordam beraman."), "Albatta, yordam beraman.")
        self.assertEqual(latin.shown("Привет! Как дела?"), "Привет! Как дела?")  # Russian is not Uzbek to respell
        cyrillic = assistant.Talk().turn("Раҳмат, яхши!")
        self.assertEqual(cyrillic.shown("Албатта, ёрдам бераман."), "Албатта, ёрдам бераман.")  # already right
        self.assertEqual(cyrillic.shown("Send the weekly report now."), "Send the weekly report now.")  # English is left readable
        for other in ("What should I do now?", "Как дела?", "Voy a casa mañana, no me esperes"):
            turn = assistant.Talk().turn(other)
            self.assertEqual(turn.sent, other)
            self.assertEqual(turn.shown("Salom! Привет! Hello!"), "Salom! Привет! Hello!")  # other languages pass untouched

    def test_an_answer_is_shown_word_by_word_while_it_arrives(self):
        from workcat import assistant

        turn = assistant.Talk().turn("Эртага эслат")
        self.assertEqual(turn.live("Albatta, ertaga so"), "Албатта, эртага ")  # "so" may yet become "soat" or "so'ng"
        self.assertEqual(turn.live("Alb"), "")
        self.assertEqual(turn.live("Albatta, ertaga soat 10 da "), "Албатта, эртага соат 10 да ")
        english = assistant.Talk().turn("Remind me tomorrow")
        self.assertEqual(english.live("Sure, I wi"), "Sure, I wi")  # nothing to respell: show every letter

    def test_conversation_and_prompt(self):
        from workcat import assistant

        talk = assistant.Talk()
        for i in range(10):
            talk.add(talk.turn(f"what about number {i}?"), f'{{"reply": "a{i}"}}')
        sent = talk.messages("SYSTEM", talk.turn("what is new today?"))
        self.assertEqual(sent[0], {"role": "system", "content": "SYSTEM"})
        self.assertEqual(sent[-1], {"role": "user", "content": "what is new today?\n\n(Answer in English.)"})
        self.assertEqual(len(sent), assistant.Talk.KEEP + 2)
        self.assertEqual(sent[1]["content"], "what about number 4?")  # the oldest lines were forgotten, and old lines carry no note
        lasting, moment = assistant.system_prompt("Miso", "Proud", "3 focus rounds today!", 25, assistant.facts_text(["Now: Thursday.", "", "Open  tasks: none."]))
        self.assertNotIn("Thursday", lasting)  # what changes with the clock stays out of the lasting part
        self.assertNotIn("proud", lasting)
        prompt = lasting + "\n\n" + moment
        self.assertIn("You are Miso", prompt)
        self.assertIn("Your mood right now: proud (3 focus rounds today!)", prompt)
        self.assertIn("use 25 if they give no length", prompt)
        self.assertIn("- Now: Thursday.\n- Open tasks: none.", prompt)
        self.assertEqual(assistant.SCHEMA["required"], list(assistant.SCHEMA["properties"]))  # every field, every time
        for field in assistant.SCHEMA["properties"]:
            self.assertIn(f'"{field}"', prompt)

    def test_times_written_by_the_model(self):
        now = dt.datetime(2026, 11, 12, 14, 0)
        when = lambda text: (lambda d: d and d.strftime("%m-%d %H:%M"))(tasks.parse_when(text, now))
        self.assertEqual(when("15:30"), "11-12 15:30")
        self.assertEqual(when("today 15:30"), "11-12 15:30")
        self.assertEqual(when("09:00"), "11-13 09:00")
        self.assertEqual(when("tomorrow 09:00"), "11-13 09:00")
        self.assertEqual(when("in 20 min"), "11-12 14:20")
        self.assertEqual(when("in 2 hours"), "11-12 16:00")
        self.assertEqual(when("2026-12-01 08:15"), "12-01 08:15")
        self.assertEqual(when("2026-13-45 99:99"), None)
        self.assertEqual(when(""), None)
        self.assertEqual(when("sometime soon"), None)


class LearningTest(unittest.TestCase):
    def test_where_you_go_next(self):
        self.assertEqual(brain.next_place({"excel": 6, "chrome": 3}), "excel")
        self.assertIsNone(brain.next_place({"excel": 3, "chrome": 1}))  # too few times to call it a habit
        self.assertIsNone(brain.next_place({"a": 4, "b": 4, "c": 4}))  # no favourite
        self.assertIsNone(brain.next_place({}))

    def test_your_own_break_rhythm(self):
        self.assertIsNone(brain.own_stretch([2400] * 5))
        self.assertEqual(brain.own_stretch([1800, 2400, 2400, 2400, 2400, 2700, 3000, 3600, 120]), 2400)  # the short one is not a work stretch
        self.assertEqual(brain.break_after(50, None), 3000)
        self.assertEqual(brain.break_after(0, 2400), 0)  # switched off stays off
        self.assertEqual(brain.break_after(50, 2400), 2400 * brain.EARLY)  # sooner, because you usually pause sooner
        self.assertEqual(brain.break_after(50, 6000), 3000)  # never later than your setting
        self.assertEqual(brain.break_after(50, 600), 1500)  # never before 25 minutes
        self.assertEqual(brain.break_after(50, 2400, adaptive=False), 3000)

    def test_moves_and_answers_are_remembered(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            for _ in range(3):
                store.add_move("gmail", "excel")
            store.add_move("gmail", "chrome")
            self.assertEqual(store.moves_from("gmail"), {"excel": 3, "chrome": 1})
            self.assertEqual(store.moves_from("word"), {})
            self.assertEqual(store.answers("routine:excel")["streak"], 0)
            store.answer("routine:excel", False)
            self.assertEqual(store.answer("routine:excel", False)["streak"], 2)
            record = store.answer("routine:excel", True)  # one yes ends the run of refusals
            self.assertEqual((record["yes"], record["no"], record["streak"]), (1, 2, 0))
            store.put("bond", 42)
            store.forget_learning()
            self.assertEqual((store.moves_from("gmail"), store.answers("routine:excel")["no"], store.get("bond")), ({}, 0, 42))
            store.close()

    def test_going_from_place_to_place_is_noticed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            tracker = Tracker(store)
            gmail = apps.Place("site:gmail", "Gmail", "office", "")
            excel = apps.Place("excel", "Excel", "office", "")
            shell = apps.Place("explorer", "File Explorer", "system", "")
            t = dt.datetime(2026, 11, 12, 9, 0).timestamp()
            for place, seconds in ((gmail, 120), (excel, 120), (shell, 90), (gmail, 20), (excel, 90)):
                for step in range(0, seconds, 5):
                    tracker.sample(t + step, 0, place)
                t += seconds
            # gmail -> excel after two minutes counts; a glance (20 s) and Windows itself do not
            self.assertEqual(store.moves_from("site:gmail"), {"excel": 1})
            self.assertEqual(store.moves_from("excel"), {})
            store.close()


class MediaTest(unittest.TestCase):
    def test_kinds_and_names(self):
        self.assertEqual(media.kind_of("Spotify.exe"), "music")
        self.assertEqual(media.kind_of("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"), "music")
        self.assertEqual(media.kind_of("Chrome"), "web")
        self.assertEqual(media.kind_of("308046B0AF4A39CB"), "web")
        self.assertEqual(media.kind_of("vlc.exe"), "video")
        self.assertEqual(media.kind_of("powershell.exe"), "media")
        self.assertEqual(media.source_name("MSEdge"), "Edge")
        self.assertEqual(media.source_name("308046B0AF4A39CB"), "Firefox")

    def test_search_links(self):
        self.assertEqual(media.youtube_search("lo-fi & chill"), "https://www.youtube.com/results?search_query=lo-fi+%26+chill")
        self.assertEqual(media.spotify_search("Lo-Fi Cat"), "spotify:search:Lo-Fi%20Cat")

    def test_play_log(self):
        saved = []

        class FakeStore:
            def add_play(self, *row):
                saved.append(row)

        log = media.PlayLog(FakeStore())
        song = media.NowPlaying("Spotify.exe", "Song", "Artist", True)
        for t in range(0, 100, 8):
            log.update(1000 + t, song)
        self.assertTrue(log.playing)
        log.update(1104, media.NowPlaying("Spotify.exe", "Next", "Artist", True))  # the track changed
        self.assertEqual(saved, [(1000, 1096, "Spotify.exe", "Song", "Artist", "music")])
        log.update(1112, media.NowPlaying("Spotify.exe", "Next", "Artist", False))  # skipped after 8 s
        self.assertEqual(len(saved), 1)
        self.assertFalse(log.playing)
        log.update(1120, None)
        log.update(1128, media.NowPlaying("chrome", "", "", True))  # playing, but nothing to call it
        self.assertFalse(log.playing)


class StoreAndTrackerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.excel = apps.Place("excel", "Excel", "office", r"C:\excel.exe")
        self.word = apps.Place("winword", "Word", "office", r"C:\winword.exe")
        self.t0 = dt.datetime(2026, 11, 12, 9, 30).timestamp()

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def run_samples(self, tracker, start, seconds, place, idle=0.0, away=False):
        events = {}
        for t in range(0, seconds + 1, 5):
            events.update(tracker.sample(start + t, idle, place, away))
        return events

    def test_slots(self):
        self.assertEqual(slot_of(self.t0), 38)
        self.assertEqual(slot_label(38), "09:30")
        self.assertEqual(day_of(self.t0), "2026-11-12")

    def test_time_is_counted_while_you_are_there(self):
        tracker = Tracker(self.store)
        events = self.run_samples(tracker, self.t0, 600, self.excel)
        self.assertEqual(events["moved"], self.excel)
        self.assertEqual(tracker.day_totals("2026-11-12"), {"excel": 600})
        self.assertEqual(tracker.streak, 600)
        tracker.flush()
        self.assertEqual(self.store.usage("2026-11-12", "2026-11-12"), {"2026-11-12": {"excel": {38: 600}}})
        self.assertEqual(self.store.places()["excel"]["name"], "Excel")

    def test_idle_time_is_not_counted_and_a_long_pause_is_a_break(self):
        tracker = Tracker(self.store)
        self.run_samples(tracker, self.t0, 900, self.excel)
        self.run_samples(tracker, self.t0 + 905, 120, self.excel, idle=100)  # a short pause: still the same stretch
        self.assertEqual(tracker.streak, 900)
        self.run_samples(tracker, self.t0 + 1030, 200, self.excel, idle=200)
        self.assertEqual(tracker.streak, 0)
        self.assertEqual(self.store.count("break"), 1)
        events = self.run_samples(tracker, self.t0 + 1235, 10, self.word)
        self.assertGreaterEqual(events["returned"], 180)
        self.assertEqual(events["moved"], self.word)
        self.assertEqual(tracker.day_totals("2026-11-12")["excel"], 900)

    def test_locked_screen_is_away(self):
        tracker = Tracker(self.store)
        self.run_samples(tracker, self.t0, 60, self.excel, away=True)
        self.assertEqual(tracker.day_totals("2026-11-12"), {})

    def test_nothing_is_saved_when_learning_is_off(self):
        tracker = Tracker(self.store, learn=False)
        self.run_samples(tracker, self.t0, 300, self.excel)
        tracker.flush()
        self.assertEqual(self.store.usage("2026-11-12", "2026-11-12"), {})
        self.assertEqual(self.store.places(), {})
        self.assertEqual(tracker.streak, 300)  # break reminders still work

    def test_your_own_category_wins(self):
        tracker = Tracker(self.store)
        self.run_samples(tracker, self.t0, 10, self.excel)
        self.store.set_category("excel", "study")
        self.store.see_place("excel", "Excel", "office", "", 1)  # seen again with the built-in guess
        self.assertEqual(self.store.places()["excel"]["category"], "study")
        self.assertEqual(Tracker(self.store).category(self.excel), "study")

    def test_recent_places(self):
        tracker = Tracker(self.store)
        self.run_samples(tracker, self.t0, 120, self.excel)
        self.run_samples(tracker, self.t0 + 3 * 3600, 120, self.word)
        self.assertEqual(tracker.recent_places(self.t0 + 3 * 3600 + 130), {"winword"})

    def test_settings_survive_bad_values(self):
        self.store.settings["name"] = "Luna"
        self.store.save_settings()
        text = self.store.settings_path.read_text(encoding="utf-8").replace('"focus_min": 25', '"focus_min": "lots"')
        self.store.settings_path.write_text(text, encoding="utf-8")
        again = Store(Path(self.folder.name))
        self.assertEqual((again.settings["name"], again.settings["focus_min"]), ("Luna", 25))
        again.close()

    def test_tasks_mutes_and_forgetting(self):
        store = self.store
        first = store.add_task("Report", due=5000)
        second = store.add_task("Backup", place="excel", repeat=True)
        self.assertEqual([t["id"] for t in store.tasks()], [first, second])
        store.update_task(first, done=6000)
        self.assertEqual([t["id"] for t in store.tasks()], [second])
        self.assertEqual(len(store.tasks(include_done=True)), 2)
        self.assertEqual(store.done_today(5500), 1)
        store.mute("routine:excel")
        store.mute("media:usual", until=100)
        self.assertTrue(store.muted("routine:excel", now=10**9))
        self.assertFalse(store.muted("media:usual", now=200))
        store.unmute("routine:excel")
        self.assertFalse(store.muted("routine:excel"))
        store.add_usage({("2026-11-12", 38, "excel"): 60})
        store.add_play(1, 100, "app", "t", "a", "music")
        store.log("focus_done", {"minutes": 25}, ts=50)
        self.assertEqual(store.events("focus_done"), [(50, {"minutes": 25})])
        store.put("greeted", "2026-11-12")
        store.forget_learning()
        self.assertEqual((store.usage("2026-01-01", "2026-12-31"), store.plays(0), store.get("greeted")), ({}, [], None))
        self.assertEqual(len(store.tasks(include_done=True)), 2)  # tasks are yours, not "learned"


class IconTest(unittest.TestCase):
    def test_icon_file(self):
        from workcat import tray

        with tempfile.TemporaryDirectory() as folder:
            data = tray.write_icon(Path(folder) / "cat.ico", "ginger").read_bytes()
        self.assertEqual(data[:6], b"\x00\x00\x01\x00\x03\x00")
        self.assertEqual([data[6 + 16 * i] for i in range(3)], [16, 32, 48])


if __name__ == "__main__":
    unittest.main()
