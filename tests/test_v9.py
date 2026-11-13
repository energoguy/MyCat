"""Tests for what 0.9 added: habits, goals with a typed percentage, the quiz about the
person's own day, reading a window from its picture, and the small things around them."""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import try_reader  # noqa: E402
from test_v7 import Scripted  # noqa: E402
from workcat import app as app_module  # noqa: E402
from workcat import extras, panel, reader, win32  # noqa: E402
from workcat.store import Store  # noqa: E402

DAY = dt.date(2026, 11, 13)  # a Friday


class WithStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()


class HabitsTest(WithStore):
    def test_kept_day_by_day(self):
        read = self.store.add_habit("Read 20 minutes")
        walk = self.store.add_habit("Walk")
        self.assertEqual([habit["name"] for habit in self.store.habits()], ["Read 20 minutes", "Walk"])
        for back in (0, 1, 2, 4):
            self.store.mark_habit(read, (DAY - dt.timedelta(days=back)).isoformat())
        self.store.mark_habit(read, DAY.isoformat())  # twice is once
        self.assertEqual(len(self.store.habit_days(read)), 4)
        self.assertEqual(extras.streak(self.store.habit_days(read), DAY), 3)  # the day before the gap does not count
        self.store.mark_habit(read, DAY.isoformat(), False)
        self.assertEqual(extras.streak(self.store.habit_days(read), DAY), 2)  # today is still open: yesterday's run stands
        self.assertEqual(extras.streak(self.store.habit_days(walk), DAY), 0)
        self.store.delete_habit(read)
        self.assertEqual(([habit["name"] for habit in self.store.habits()], self.store.habit_days(read)), (["Walk"], set()))

    def test_todays_goals_are_untouched_by_the_longer_ones(self):
        self.store.add_long_goal("week", "2026-W46", "Finish the report")
        self.assertEqual(self.store.goals(DAY.isoformat()), [])  # the day's three goals are another thing


class GoalsTest(WithStore):
    def test_periods(self):
        self.assertEqual([extras.period(span, DAY) for span in ("week", "month", "year")], ["2026-W46", "2026-11", "2026"])
        self.assertEqual(extras.period("week", dt.date(2027, 1, 1)), "2026-W53")  # the week a day belongs to, not the year it is in

    def test_a_percentage_typed_by_the_person(self):
        goal = self.store.add_long_goal("month", "2026-11", "Finish the yearly report")
        self.assertEqual(self.store.long_goal(goal)["progress"], 0)
        for typed, kept in ((70, 70), (250, 100), (-5, 0)):
            self.store.set_long_goal(goal, typed)
            self.assertEqual(self.store.long_goal(goal)["progress"], kept)

    def test_what_is_not_done_is_carried_over(self):
        old = self.store.add_long_goal("month", "2026-10", "Learn to swim")
        done = self.store.add_long_goal("month", "2026-10", "Paint the fence")
        self.store.set_long_goal(done, 100)
        new = self.store.add_long_goal("month", "2026-11", "Finish the yearly report")
        self.store.add_long_goal("year", "2026", "Run a marathon")
        self.assertEqual([goal["id"] for goal in extras.current_goals(self.store, "month", DAY)], [old, new])  # the finished one of October is gone
        self.store.set_long_goal(new, 100)
        self.assertEqual([goal["id"] for goal in extras.current_goals(self.store, "month", DAY)], [old, new])  # done this month: still shown this month
        self.assertEqual(len(extras.current_goals(self.store, "year", DAY)), 1)

    def test_the_ai_is_told(self):
        self.assertEqual(extras.goal_facts(self.store, DAY), [])
        habit = self.store.add_habit("Read 20 minutes")
        self.store.mark_habit(habit, DAY.isoformat())
        self.store.add_habit("Walk")
        goal = self.store.add_long_goal("month", "2026-11", "Finish the yearly report")
        self.store.set_long_goal(goal, 70)
        lines = extras.goal_facts(self.store, DAY)
        self.assertIn("Read 20 minutes (done); Walk (not yet)", lines[0])
        self.assertIn("goals for this month", lines[1])
        self.assertIn("Finish the yearly report (70 %)", lines[1])

    def test_said_in_chat(self):
        report = self.store.add_long_goal("month", "2026-11", "Finish the yearly report")
        self.store.add_long_goal("year", "2026", "Run a marathon")
        self.store.add_long_goal("week", "2026-W46", "Ҳисоботни топшириш")
        wish = lambda said: extras.progress_wish(self.store, said, DAY)  # noqa: E731
        for said, percent in (("The yearly report goal is at 70 %", 70), ("report: 45 percent done", 45), ("Отчёт готов на 30 процентов", None), ("my marathon training is at 5%", 5)):
            found = wish(said)
            self.assertEqual(found and found[1], percent, said)
        self.assertEqual(wish("The yearly report goal is at 70 %")[0]["id"], report)
        self.assertEqual(wish("Ҳисобот 55 фоиз тайёр")[1], 55)  # Uzbek, and the goal written in the same letters
        for said in (
            "Is the report at 70 %?",  # a question sets nothing
            "The report and the marathon are at 70 %",  # two goals: which one is not guessed
            "The report is nearly done", "I am 70 % sure", "The report is at 170 %", "Battery at 70 %, report at 80 %",
        ):
            self.assertIsNone(wish(said), said)


class GoalWishTest(WithStore):
    def cat(self):
        cat = Scripted(self.store)
        cat.goal_wish = app_module.App.goal_wish.__get__(cat)
        return cat

    def test_set_with_undo_or_only_offered_or_not_at_all(self):
        goal = self.store.add_long_goal("month", extras.period("month", dt.date.today()), "Finish the yearly report")
        cat = self.cat()
        cat.settings.update(ai_may_edit=True, ai_ask_first=False)
        notes = cat.goal_wish("The yearly report goal is at 70 %")
        self.assertEqual((self.store.long_goal(goal)["progress"], notes[0]["text"]), (70, 'Goal "Finish the yearly report": 70 %'))
        notes[0]["undo"]()
        self.assertEqual(self.store.long_goal(goal)["progress"], 0)
        cat.settings["ai_ask_first"] = True  # asked first: a button, and nothing changed until it is pressed
        notes = cat.goal_wish("The yearly report goal is at 70 %")
        self.assertEqual((self.store.long_goal(goal)["progress"], notes[0]["mark"]), (0, "?"))
        self.assertEqual(notes[0]["do"]()["text"], 'Goal "Finish the yearly report": 70 %')
        self.assertEqual(self.store.long_goal(goal)["progress"], 70)
        self.assertEqual(cat.goal_wish("The yearly report goal is at 70 %"), [])  # it is there already
        cat.settings.update(ai_may_edit=False, ai_ask_first=False)  # changing things is switched off
        self.assertEqual((cat.goal_wish("The yearly report goal is at 90 %"), self.store.long_goal(goal)["progress"]), ([], 70))


class QuizTest(WithStore):
    def app(self):
        return type("App", (), {"store": self.store, "today": DAY.isoformat()})()

    def test_sums_where_nothing_was_seen(self):
        questions = extras.day_questions(self.app())
        self.assertEqual(len(questions), 5)
        for question, choices, right in questions:
            self.assertIn(right, choices, question)
            self.assertEqual(len(set(choices)), len(choices), question)

    def test_about_yesterday_where_something_was(self):
        yesterday = (DAY - dt.timedelta(days=1)).isoformat()
        for place, name, seconds in (("excel", "Excel", 7200), ("chrome", "Chrome", 3600), ("code", "VS Code", 1800), ("notepad", "Notepad", 300)):
            self.store.db.execute("INSERT INTO places (place, name, category, path) VALUES (?, ?, 'office', '')", (place, name))
            self.store.db.execute("INSERT INTO usage (day, slot, place, seconds) VALUES (?, 20, ?, ?)", (yesterday, place, seconds))
        self.store.db.commit()
        task = self.store.add_task("Send the weekly report")
        self.store.update_task(task, done=int(dt.datetime.combine(DAY - dt.timedelta(days=1), dt.time(15)).timestamp()))
        self.store.add_task("Call the bank")
        found = {}
        for _ in range(12):  # five of the possible questions are drawn each time
            for question, choices, right in extras.day_questions(self.app()):
                self.assertIn(right, choices, question)
                found[question] = right
        self.assertEqual(found["Which program or site did you spend the most time in yesterday?"], "Excel")
        self.assertEqual(found["Which of these did you use the least yesterday?"], "Notepad")
        self.assertEqual(found["How many tasks did you finish yesterday?"], "1")
        self.assertEqual(found["Which of these did you finish yesterday?"], "Send the weekly report")
        self.assertEqual(found["How long were you at the computer yesterday?"], "about 4 h")
        self.assertEqual(found["How many tasks are open on your list right now?"], "1")


class PictureTest(unittest.TestCase):
    def test_a_window_that_gives_no_text_is_read_from_its_picture(self):
        helper, hwnd = try_reader.started()
        real = reader.text_of
        reader.text_of = lambda *a, **k: ("", "nothing")  # as with a program that tells a screen reader nothing
        try:
            words = reader.picture_text(hwnd)
            seen = reader.read(hwnd)
        finally:
            reader.text_of = real
            helper.kill()
        if not words:
            self.skipTest("this Windows has no text recognition (or no language for it)")
        self.assertIn("quarterly report", words.lower())
        self.assertNotIn("hunter2", words)  # a password field shows dots, and dots are all a picture has
        self.assertEqual((seen.how, seen.why), ("picture", ""))
        self.assertIn("report", seen.text.lower())

    def test_where_there_is_nothing_to_photograph(self):
        self.assertEqual(reader.picture_text(0), "")


class SmallThingsTest(unittest.TestCase):
    def test_voice_typing_is_windows_own(self):
        pressed = []
        real = win32.user32.keybd_event
        win32.user32.keybd_event = lambda key, scan, flag, extra: pressed.append((key, flag))
        try:
            win32.voice_typing()
        finally:
            win32.user32.keybd_event = real
        self.assertEqual(pressed, [(0x5B, 0), (0x48, 0), (0x48, 2), (0x5B, 2)])  # the Windows key and H, down and up

    def test_questions_for_one_click_fit_the_time_of_day(self):
        self.assertEqual([panel.part_of_day(hour) for hour in (7, 11, 12, 16, 17, 23)], ["morning", "morning", "day", "day", "evening", "evening"])
        self.assertIn("Plan my day", panel.QUICK["morning"])
        self.assertIn("What did I do today?", panel.QUICK["evening"])
        for chips in panel.QUICK.values():
            self.assertEqual((len(chips), chips[-1]), (3, "How are my goals going?"))


if __name__ == "__main__":
    unittest.main()
