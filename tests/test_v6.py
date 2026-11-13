"""Tests for what 0.6 added: the assistant's new abilities and their Undo, what the cat
keeps in mind, which brain answers when, the picking of services and models.

The online AI is only ever a pretend service on this computer (the one in test_v4).
"""
from __future__ import annotations

import datetime as dt
import json
import queue
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v4 import Pretend  # noqa: E402
from workcat import app as app_module  # noqa: E402
from workcat import apps, assistant, cloud, llm, store as store_module  # noqa: E402
from workcat.ai import AI  # noqa: E402
from workcat.store import Store  # noqa: E402


def answer(**filled) -> str:
    """What a model would send back, with every field in its place."""
    return json.dumps({**assistant._EMPTY, **filled})


class NameTest(unittest.TestCase):
    def test_a_new_cat_is_called_mitti(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            self.assertEqual(store.settings["name"], "Mitti")
            store.close()

    def test_a_cat_that_kept_the_old_usual_name_takes_the_new_one_once(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "settings.json").write_text(json.dumps({"name": "Miso", "first_run_done": True}), encoding="utf-8")
            store = Store(Path(folder))
            self.assertEqual(store.settings["name"], "Mitti")
            store.settings["name"] = "Miso"  # ... and whoever now calls it Miso on purpose keeps that
            store.save_settings()
            store.close()
            store = Store(Path(folder))
            self.assertEqual(store.settings["name"], "Miso")
            store.forget_learning()  # forgetting what was learned does not rename the cat either
            store.close()
            store = Store(Path(folder))
            self.assertEqual(store.settings["name"], "Miso")
            store.close()

    def test_a_name_someone_chose_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "settings.json").write_text(json.dumps({"name": "Barsik"}), encoding="utf-8")
            store = Store(Path(folder))
            self.assertEqual(store.settings["name"], "Barsik")
            store.close()


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_notes_are_kept_once_and_can_be_taken_back(self):
        store = self.store
        first = store.add_note("  The user's manager   is Aziz. ")
        self.assertTrue(first)
        self.assertEqual(store.add_note("the user's manager is aziz."), 0)  # known already
        self.assertEqual(store.add_note("   "), 0)
        second = store.add_note("The user works at a bank.")
        self.assertEqual([note["text"] for note in store.notes()], ["The user's manager is Aziz.", "The user works at a bank."])
        kept = store.notes()[0]
        store.delete_note(first)
        self.assertEqual([note["id"] for note in store.notes()], [second])
        store.restore_note(kept)
        self.assertEqual([note["id"] for note in store.notes()], [first, second])
        store.clear_notes()
        self.assertEqual(store.notes(), [])

    def test_the_oldest_notes_make_room(self):
        for i in range(store_module.NOTES_KEPT + 5):
            self.store.add_note(f"Fact number {i}.")
        notes = self.store.notes()
        self.assertEqual(len(notes), store_module.NOTES_KEPT)
        self.assertEqual(notes[0]["text"], "Fact number 5.")

    def test_the_conversation_outlasts_the_app_up_to_a_point(self):
        for i in range(store_module.TALK_KEPT + 6):
            self.store.add_talk("en", "user" if i % 2 == 0 else "assistant", f"line {i}", f"shown {i}")
        rows = self.store.talk()
        self.assertEqual(len(rows), store_module.TALK_KEPT)
        self.assertEqual((rows[0]["content"], rows[-1]["shown"]), ("line 6", f"shown {store_module.TALK_KEPT + 5}"))
        talk = assistant.Talk()
        talk.load(rows)
        self.assertEqual(len(talk.history), assistant.Talk.KEEP * 3)
        self.assertEqual(talk.history[-1], ("en", {"role": "assistant", "content": f"line {store_module.TALK_KEPT + 5}"}))
        self.store.clear_talk()
        self.assertEqual(self.store.talk(), [])

    def test_forgetting_what_was_learned_takes_notes_and_talk_along(self):
        self.store.add_note("The user likes tea.")
        self.store.add_talk("en", "user", "hello", "hello")
        task = self.store.add_task("Stays")
        self.store.forget_learning()
        self.assertEqual((self.store.notes(), self.store.talk()), ([], []))
        self.assertEqual(self.store.task(task)["text"], "Stays")

    def test_a_deleted_task_comes_back_as_it_was(self):
        task_id = self.store.add_task("Call the bank", due=1_800_000_000, goal="2026-11-13")
        self.store.update_task(task_id, tries=2, shown=1_700_000_000)
        before = self.store.task(task_id)
        self.store.delete_task(task_id)
        self.assertIsNone(self.store.task(task_id))
        self.store.restore_task(before)
        self.assertEqual(self.store.task(task_id), before)
        self.store.update_task(task_id, done=1_800_000_500)
        self.assertEqual([task["text"] for task in self.store.finished(1_800_000_000)], ["Call the bank"])
        self.assertEqual(self.store.finished(1_800_001_000), [])


class KeysAndModelsTest(unittest.TestCase):
    def test_a_key_says_whose_it_is(self):
        self.assertEqual(cloud.guess_service("sk-ant-usr-abc"), "claude")
        self.assertEqual(cloud.guess_service("  sk-or-v1-abc "), "openrouter")
        self.assertEqual(cloud.guess_service("gsk_abc"), "groq")
        self.assertEqual(cloud.guess_service("AIzaSyAbc"), "gemini")
        self.assertEqual(cloud.guess_service("sk-proj-abc"), "openai")
        self.assertEqual(cloud.guess_service("sk-abc"), "")  # several services write theirs like this
        self.assertEqual(cloud.guess_service(""), "")

    def test_a_sensible_model_is_picked_when_nobody_picked(self):
        pick = cloud.pick_default
        self.assertEqual(pick("claude", []), "claude-opus-5-5")  # Claude's are known
        self.assertEqual(pick("openai", ["gpt-4o", "gpt-4o-mini", "gpt-5-mini", "gpt-5.2-mini", "gpt-5.2", "text-embedding-3-small", "gpt-5.2-mini-2026-01-01", "whisper-1"]), "gpt-5.2-mini")
        self.assertEqual(pick("openai", ["gpt-4o", "gpt-4o-mini", "dall-e-3"]), "gpt-4o-mini")
        self.assertEqual(pick("gemini", ["gemini-2.5-flash", "gemini-3-flash", "gemini-3-pro", "gemini-3-flash-image", "embedding-001"]), "gemini-3-flash")
        self.assertEqual(pick("groq", ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "whisper-large-v3"]), "llama-3.3-70b-versatile")
        self.assertEqual(pick("deepseek", ["deepseek-reasoner", "deepseek-chat"]), "deepseek-chat")
        self.assertEqual(pick("openrouter", ["meta/llama", "openrouter/auto", "openai/gpt-5-mini"]), "openrouter/auto")
        self.assertEqual(pick("other", ["text-embed-9", "zeta-chat", "alpha-chat"]), "zeta-chat")  # the first one that is for talking
        self.assertEqual(pick("other", ["only-embed"]), "only-embed")  # better a doubtful one than none
        self.assertEqual(pick("other", []), "")

    def test_claudes_models_have_plain_names(self):
        self.assertEqual(list(cloud.PLAIN_NAMES), list(cloud.SERVICES["claude"].models))
        self.assertIn("Opus 5.5", cloud.PLAIN_NAMES["claude-opus-5-5"])


class AnswerShapeTest(unittest.TestCase):
    def test_every_new_field_becomes_an_action(self):
        reply, actions = assistant.parse(answer(
            reply="ok", done=[4, "7", 4, 0, -1, True], move=[{"task": 7, "when": "tomorrow 10:00"}, {"task": 8, "when": ""}, "x"], remove=[9],
            goals=["Report", "Bank", "Walk", "A fourth"], open=["Excel", "", "Excel"], search="  flights to   Tashkent ", remember=["The user likes tea."], forget=[2],
        ))
        self.assertEqual(reply, "ok")
        self.assertEqual(actions, [
            {"do": "done", "task": 4}, {"do": "done", "task": 7}, {"do": "move", "task": 7, "when": "tomorrow 10:00"}, {"do": "remove", "task": 9},
            {"do": "goals", "items": ["Report", "Bank", "Walk"]}, {"do": "open", "name": "Excel"}, {"do": "search", "query": "flights to Tashkent"},
            {"do": "remember", "text": "The user likes tea."}, {"do": "forget", "note": 2},
        ])

    def test_an_answer_of_the_old_shape_still_reads(self):
        raw = json.dumps({"reply": "Sure", "reminders": [{"text": "call mom", "when": "09:00"}], "focus_minutes": 25, "start_break": False, "suggestions": ["Khruangbin"]})
        reply, actions = assistant.parse(raw)
        self.assertEqual([action["do"] for action in actions], ["remind", "focus", "suggest"])
        self.assertEqual(assistant.parse('{"reply": "hi", "done": "all", "open": 5, "search": ["x"], "forget": null}'), ("hi", []))

    def test_the_examples_in_the_instructions_have_the_shape(self):
        lasting, _moment = assistant.system_prompt("Mitti", "Content", "why", 25, "")
        examples = [line[5:] for line in lasting.splitlines() if line.startswith("You: ")]
        self.assertEqual(len(examples), 5)
        for example in examples:
            self.assertEqual(list(json.loads(example)), list(assistant.SCHEMA["properties"]))
        self.assertGreater(len(lasting), 3000)  # long enough for an online service to keep between questions

    def test_what_is_switched_off_is_said_to_the_model(self):
        lasting, _ = assistant.system_prompt("Mitti", "Content", "why", 25, "", off=("open", "memory"), ask_first=True)
        self.assertIn('Leave "open", "search", "remember", "forget" empty', lasting)
        self.assertIn("confirms each action with a button", lasting)
        plain, _ = assistant.system_prompt("Mitti", "Content", "why", 25, "")
        self.assertNotIn("switched off", plain)
        self.assertNotIn("confirms each action", plain)
        for style, words in (("plain", "to the point"), ("friendly", "attentive friend"), ("nothing-like-it", "playful")):
            self.assertIn(words, assistant.system_prompt("Mitti", "Content", "why", 25, "", style=style)[0])
        self.assertIn("one or two short sentences", assistant.system_prompt("Mitti", "Content", "why", 25, "", length="short")[0])

    def test_the_two_parts_travel_as_two_messages(self):
        talk = assistant.Talk()
        sent = talk.messages(("LASTING", "NOW"), talk.turn("hello there, how are you?"))
        self.assertEqual([message["role"] for message in sent], ["system", "system", "user"])
        self.assertEqual(llm.one_system(sent)[0], {"role": "system", "content": "LASTING\n\nNOW"})
        self.assertEqual(len(llm.one_system(sent)), 2)
        one = [{"role": "system", "content": "A"}, {"role": "user", "content": "b"}]
        self.assertIs(llm.one_system(one), one)


class CarefulTest(unittest.TestCase):
    """What a small model wants done is held against what the person wrote."""

    def turn(self, text: str, careful: bool = True, tasks=None, notes=None):
        turn = assistant.Talk().turn(text, careful=careful)
        turn.tasks = tasks or {4: "Send the report", 7: "Call the bank", 9: "Buy milk"}
        turn.notes = notes or {2: "The user's manager is Aziz."}
        return turn

    def test_only_what_the_message_asks_for_and_names(self):
        turn = self.turn("I sent the report, and move the bank call to tomorrow 10")
        _, actions = turn.result(answer(reply="ok", done=[4, 9], move=[{"task": 7, "when": "tomorrow 10:00"}], open=["Excel"], remove=[9]))
        self.assertEqual(actions, [{"do": "done", "task": 4}, {"do": "move", "task": 7, "when": "tomorrow 10:00"}])

    def test_small_talk_changes_nothing(self):
        turn = self.turn("how are you?")
        _, actions = turn.result(answer(reply="fine", done=[4], open=["Chrome"], search="cats", remember=["The user is fine."], forget=[2], goals=["x"]))
        self.assertEqual(actions, [])

    def test_a_task_that_is_not_named_is_not_guessed(self):
        _, actions = self.turn("I finished it").result(answer(reply="Ticked off!", done=[4]))
        self.assertEqual(actions, [{"do": "unsure"}])  # the app then says that nothing was changed
        _, actions = self.turn("task 4 is done").result(answer(reply="ok", done=[4]))
        self.assertEqual(actions, [{"do": "done", "task": 4}])  # its number names it too

    def test_a_number_that_was_not_on_the_list_is_nobodys_task(self):
        for careful in (True, False):
            _, actions = self.turn("delete the report task", careful).result(answer(reply="ok", remove=[5, 4], forget=[3]))
            self.assertEqual(actions, [{"do": "remove", "task": 4}])

    def test_in_russian_and_in_uzbek(self):
        turn = self.turn("Я отправил отчёт, удали задачу про молоко", tasks={4: "Отправить отчет", 9: "Купить молоко"})
        self.assertEqual(turn.result(answer(reply="ок", done=[4], remove=[9]))[1], [{"do": "done", "task": 4}, {"do": "remove", "task": 9}])
        turn = self.turn("ҳисоботни тугатдим", tasks={4: "Hisobot yuborish"})  # the task was written in the other alphabet
        self.assertEqual(turn.result(answer(reply="ok", done=[4]))[1], [{"do": "done", "task": 4}])
        turn = self.turn("Excel'ни оч ва эслаб қол: Азиз менинг раҳбарим")
        _, actions = turn.result(answer(reply="ok", open=["Excel"], remember=["azizning rahbari"]))
        self.assertEqual([action["do"] for action in actions], ["open", "remember"])

    def test_finished_is_said_with_a_verb_in_the_past(self):
        """Found with the real model: "I watered the plants", "проверил отчёт", "ҳисоботни
        текширдим" say that something is done without any word like "done"."""
        tasks = {4: "Send the weekly report", 9: "Water the plants", 12: "Купить молоко", 15: "Hisobotni tekshirish", 16: "Проверить отчёт"}
        for said, number in (
            ("I watered the plants", 9), ("I mailed the weekly report this morning", 4), ("I wrote the weekly report", 4),
            ("Я купил молоко", 12), ("Молоко куплено", 12), ("Проверила отчёт", 16), ("Отчёт проверен", 16),
            ("Ҳисоботни текширдим", 15), ("Hisobotni tekshirdim", 15), ("Hisobot tekshirildi", 15),
        ):
            self.assertEqual(self.turn(said, tasks=tasks).result(answer(reply="ok", done=[number]))[1], [{"do": "done", "task": number}], said)
        for said, number in (  # the task is named, but nothing says that it is finished: it stays as it is
            ("I need to send the weekly report", 4), ("What about the plants?", 9), ("Мне нужен отчёт", 16), ("Я должен купить молоко", 12),
            ("Hisobotni tekshirish kerak", 15),
        ):
            self.assertEqual(self.turn(said, tasks=tasks).result(answer(reply="ok", done=[number]))[1], [], said)

    def test_nothing_is_filed_twice(self):
        """Also from the real model: a task that is moved came back as a new reminder too,
        a fact to remember as a task as well, and a question about the day as a reminder."""
        turn = self.turn("Move the bank call to tomorrow at 9")
        _, actions = turn.result(answer(reply="ok", move=[{"task": 7, "when": "tomorrow 09:00"}], reminders=[{"text": "Call the bank", "when": "tomorrow 09:00"}]))
        self.assertEqual(actions, [{"do": "move", "task": 7, "when": "tomorrow 09:00"}])
        turn = self.turn("Эслаб қол: мен банкда ишлайман")
        _, actions = turn.result(answer(reply="ok", reminders=[{"text": "Remember: I work at a bank", "when": ""}], remember=["Eslab qol: men bankda ishlayman"]))
        self.assertEqual(actions, [{"do": "remember", "text": "Мен банкда ишлайман"}])
        turn = self.turn("Remember to call mom tomorrow at 9")  # with a time it is a reminder, not a fact about the person
        _, actions = turn.result(answer(reply="ok", reminders=[{"text": "Call mom", "when": "tomorrow 09:00"}], remember=["The user must call mom."]))
        self.assertEqual(actions, [{"do": "remind", "text": "Call mom", "when": "tomorrow 09:00"}])
        for careful, expected in ((True, []), (False, ["remind"])):  # a question is no wish to be reminded, for a small model
            turn = self.turn("Бугун нима қилишим керак?", careful)
            _, actions = turn.result(answer(reply="ok", reminders=[{"text": "Hisobotni yuborish", "when": "17:00"}]))
            self.assertEqual([action["do"] for action in actions], expected)
        turn = self.turn("Can you remind me about the oven in 20 minutes?")  # ... unless the question asks for exactly that
        _, actions = turn.result(answer(reply="ok", reminders=[{"text": "Check the oven", "when": "in 20 min"}]))
        self.assertEqual([action["do"] for action in actions], ["remind"])

    def test_what_the_model_let_pass_is_offered_never_done(self):
        """The real model answered "I bought the milk" with "I'll tick that off" and an
        empty list. The app then offers the one task the message plainly means."""
        tasks = {4: "Send the weekly report", 12: "Купить молоко", 13: "Купить хлеб", 15: "Hisobotni tekshirish"}
        nothing = answer(reply="Отлично, отмечу!")
        self.assertEqual(self.turn("Я купил молоко", tasks=tasks).result(nothing)[1], [{"do": "offer", "task": 12}])
        self.assertEqual(self.turn("Ҳисоботни текширдим", tasks=tasks).result(nothing)[1], [{"do": "offer", "task": 15}])
        self.assertEqual(self.turn("I mailed the weekly report", tasks=tasks).result(nothing)[1], [{"do": "offer", "task": 4}])
        for said in (
            "Я купил молоко и хлеб",  # two tasks are meant: which one is not guessed
            "Я купил молоко?", "Translate to Russian: the weekly report is ready",
            "Мне нужно купить молоко", "Я закончил",
        ):
            self.assertEqual(self.turn(said, tasks=tasks).result(nothing)[1], [], said)
        # Asked to delete it: that is what is offered. Asked to move it: the new time is not
        # the app's to guess, so it only says that nothing was changed.
        self.assertEqual(self.turn("Удали задачу про молоко, я его купил", tasks=tasks).result(nothing)[1], [{"do": "offer", "task": 12, "what": "remove"}])
        self.assertEqual(self.turn("Перенеси молоко на завтра, сегодня не купил", tasks=tasks).result(nothing)[1], [{"do": "nothing"}])
        self.assertEqual(self.turn("Я купил молоко", careful=False, tasks=tasks).result(nothing)[1], [])  # a big model is not second-guessed
        done = self.turn("Я купил молоко", tasks=tasks).result(answer(reply="ok", done=[12]))[1]
        self.assertEqual(done, [{"do": "done", "task": 12}])  # where the model did its part, nothing is offered on top

    def test_a_small_models_note_is_the_persons_own_sentence(self):
        for said, kept in (
            ("Remember that Aziz is my manager", "Aziz is my manager"),
            ("Запомни, что мой руководитель Азиз.", "Мой руководитель Азиз"),
            ("Эслаб қол: мен банкда ишлайман", "Мен банкда ишлайман"),
            ("Азиз менинг раҳбарим эканини эслаб қол", "Азиз менинг раҳбарим эканини"),  # the verb comes last: what stands before it
            ("My name is Timur", "My name is Timur"),
            ("Keep in mind: I leave at six on Fridays", "I leave at six on Fridays"),
        ):
            _, actions = self.turn(said).result(answer(reply="ok", remember=["Ўзинг банкда ишлайишни жуда яхши кўрасиз."]))
            self.assertEqual(actions, [{"do": "remember", "text": kept}], said)
        _, actions = self.turn("Remember that Aziz is my manager", careful=False).result(answer(reply="ok", remember=["The user's manager is Aziz."]))
        self.assertEqual(actions[0]["text"], "The user's manager is Aziz.")  # a big model words it well itself

    def test_english_in_brackets_after_a_russian_or_uzbek_answer_goes(self):
        reply = lambda said, text, careful=True: self.turn(said, careful).result(answer(reply=text))[0]
        self.assertEqual(reply("Открой калькулятор", "Я открываю калькулятор для тебя. (I’m opening the calculator for you.)"), "Я открываю калькулятор для тебя.")
        self.assertEqual(reply("Excel'ni och", "Excel ochildi! (Excel opened!),"), "Excel ochildi!")
        self.assertEqual(reply("Открой калькулятор", "Открываю (как ты и просил)."), "Открываю (как ты и просил).")  # their own language stays
        self.assertEqual(reply("Open the calculator", "Opening it (as you asked)."), "Opening it (as you asked).")
        self.assertEqual(reply("Открой калькулятор", "Открываю. (Here you go, as asked.)", careful=False), "Открываю. (Here you go, as asked.)")

    def test_a_translation_is_asked_for_in_its_own_language(self):
        english = assistant.Talk().turn("Translate to Russian: Good morning, the report is ready.")
        self.assertIn("Give the translation in the language the user asks for", english.note)
        self.assertNotIn("Answer in English", english.note)
        self.assertIn("Give the translation", assistant.Talk().turn("Переведи на английский: отчёт готов").note)
        self.assertIn("Give the translation", assistant.Talk().turn("Буни рус тилига таржима қил: ҳисобот тайёр").note)
        self.assertEqual(assistant.Talk().turn("How are you today, my friend?").note, "(Answer in English.)")

    def test_scaffolding_and_little_pictures_stay_out_of_the_reply(self):
        broken = '{"reply": "Yaxshi, eslab qoldim!“, “reminders”: [], “done”: [], “remember”: [“x”]", "reminders": [], "done": []}'
        self.assertEqual(assistant.parse(broken)[0], "Yaxshi, eslab qoldim!")
        self.assertEqual(assistant.parse(answer(reply='Sure!", "done": [4], "open": []'))[0], "Sure!")
        self.assertEqual(assistant.parse(answer(reply="Excel is opening now. Let’s get to work! 🐾"))[0], "Excel is opening now. Let’s get to work!")
        self.assertEqual(assistant.parse(answer(reply="1. First ✅ this\n2. Then 🙂 that"))[0], "1. First this\n2. Then that")
        self.assertEqual(assistant.parse(answer(reply='He said "open the door", and I did.'))[0], 'He said "open the door", and I did.')  # ordinary quoting is left alone

    def test_a_big_model_is_taken_at_its_word(self):
        turn = self.turn("that one's sorted, thanks", careful=False)
        _, actions = turn.result(answer(reply="ok", done=[4], open=["Excel"], remember=["the user thanks cats."], goals=["report"]))
        self.assertEqual(actions, [
            {"do": "done", "task": 4}, {"do": "goals", "items": ["Report"]}, {"do": "open", "name": "Excel"}, {"do": "remember", "text": "The user thanks cats."},
        ])

    def test_few_words_that_name_a_task(self):
        self.assertTrue(assistant.same_thing("report", "Send the report"))
        self.assertTrue(assistant.same_thing("Send the weekly report to Aziz", "weekly report"))
        self.assertFalse(assistant.same_thing("walk", "Send the report"))
        self.assertFalse(assistant.same_thing("", "Send the report"))
        self.assertTrue(assistant.same_thing("ҳисобот", "Hisobot yuborish"))


class Cat:
    """The parts of the app that the assistant's actions touch, without any windows."""

    run_ai_actions = app_module.App.run_ai_actions
    _ai_step = app_module.App._ai_step
    make_goals = app_module.App.make_goals
    goals_today = app_module.App.goals_today
    open_target = app_module.App.open_target
    plan_due = app_module.App.plan_due
    goals_due = app_module.App.goals_due
    asks_first = app_module.App.asks_first

    def __init__(self, store):
        self.script_now = None
        self.store, self.settings = store, store.settings
        self.settings["first_run_done"] = True
        self.today = dt.date.today().isoformat()
        self.opened, self.panels, self.offers, self.said = [], [], [], set()
        self.focus_len, self.focusing, self.resting = 0, False, False
        self.day_started = None
        self.ai = type("Brain", (), {"state": "ready", "busy": False})()

    def refresh_panel(self) -> None:
        pass

    def complete_task(self, task_id: int) -> None:
        self.store.update_task(task_id, done=int(time.time()))

    def say_once(self, key: str) -> bool:
        if key in self.said:
            return False
        self.said.add(key)
        return True

    def open_panel(self, tab: str = "today") -> None:
        self.panels.append(tab)

    def open_address(self, address: str) -> bool:
        self.opened.append(address)
        return True

    def start_focus(self, minutes=None) -> None:
        self.focus_len, self.focusing = int(minutes or self.settings["focus_min"]), True

    def stop_focus(self) -> None:
        self.focusing = False

    def start_break(self) -> None:
        self.resting = True

    def end_break(self) -> None:
        self.resting = False

    def offer(self, key, text, yes, no, never=True, emote="") -> None:
        self.offers.append((key, text, yes[0]))

    def plan_day(self) -> None:
        pass

    def ask_goals(self) -> None:
        pass


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.cat = Cat(self.store)
        self.report = self.store.add_task("Send the report")
        self.bank = self.store.add_task("Call the bank", due=int(time.time()) + 3600)
        self.shortcuts, apps.shortcuts = apps.shortcuts, lambda *a, **k: {"excel": ("Excel", r"C:\menu\Excel.lnk")}
        self.started, app_module.os.startfile = [], lambda path: self.started.append(path)

    def tearDown(self):
        apps.shortcuts = self.shortcuts
        del app_module.os.startfile
        self.store.close()
        self.folder.cleanup()

    def run_actions(self, said: str = "", **filled) -> list:
        turn = assistant.Talk().turn(said or "do it", careful=False)
        turn.tasks = {task["id"]: task["text"] for task in self.store.tasks()}
        turn.notes = {note["id"]: note["text"] for note in self.store.notes()}
        _, actions = turn.result(answer(reply="ok", **filled))
        return self.cat.run_ai_actions(actions, turn)

    def open_texts(self) -> list:
        return [task["text"] for task in self.store.tasks()]

    def test_finishing_a_task_and_taking_it_back(self):
        notes = self.run_actions(done=[self.report])
        self.assertEqual([note["text"] for note in notes], ["Finished: Send the report"])
        self.assertEqual(self.open_texts(), ["Call the bank"])
        notes[0]["undo"]()
        self.assertEqual(sorted(self.open_texts()), ["Call the bank", "Send the report"])
        self.assertEqual(self.run_actions(done=[999]), [])  # an unknown number is nobody's task
        self.assertEqual(len(self.run_actions(done=[self.report])), 1)
        self.assertEqual(self.cat.run_ai_actions([{"do": "done", "task": self.report}], None), [])  # what is finished is not finished twice

    def test_moving_a_task_and_taking_it_back(self):
        before = self.store.task(self.bank)["due"]
        notes = self.run_actions(move=[{"task": self.bank, "when": "tomorrow 10:00"}])
        moved = dt.datetime.fromtimestamp(self.store.task(self.bank)["due"])
        self.assertEqual((moved.date(), moved.hour), (dt.date.today() + dt.timedelta(days=1), 10))
        self.assertTrue(notes[0]["text"].startswith("Moved: Call the bank ("))
        notes[0]["undo"]()
        self.assertEqual(self.store.task(self.bank)["due"], before)
        notes = self.run_actions(move=[{"task": self.bank, "when": "when the moon is full"}])
        self.assertEqual((notes[0]["mark"], notes[0]["text"]), ("!", "I did not understand the new time for: Call the bank"))
        self.assertEqual(self.store.task(self.bank)["due"], before)

    def test_deleting_a_task_and_taking_it_back(self):
        before = self.store.task(self.bank)
        notes = self.run_actions(remove=[self.bank])
        self.assertEqual(notes[0]["text"], "Deleted: Call the bank")
        self.assertIsNone(self.store.task(self.bank))
        notes[0]["undo"]()
        self.assertEqual(self.store.task(self.bank), before)

    def test_goals_use_the_tasks_that_are_there(self):
        notes = self.run_actions(goals=["report", "Evening walk"])
        goals = self.store.goals(self.cat.today)
        self.assertEqual(sorted(goal["text"] for goal in goals), ["Evening walk", "Send the report"])  # no second "report"
        self.assertEqual(notes[0]["text"], "Goals for today: Report; Evening walk")
        notes[0]["undo"]()
        self.assertEqual(self.store.goals(self.cat.today), [])
        self.assertEqual(sorted(self.open_texts()), ["Call the bank", "Send the report"])

    def test_opening_only_what_is_known(self):
        notes = self.run_actions("open excel, youtube, calculator and totally-made-up", open=["excel", "YouTube", "калькулятор"])
        self.assertEqual([note["text"] for note in notes], ["Opened: Excel", "Opened: YouTube", "Opened: Calculator"])
        self.assertEqual(self.started, [r"C:\menu\Excel.lnk", "calc.exe"])  # a Start-menu shortcut, and one of Windows' own tools
        self.assertEqual(self.cat.opened, ["https://www.youtube.com"])
        notes = self.run_actions("run format c:", open=["format c: /y", r"C:\Windows\System32\cmd.exe /c del"])
        self.assertEqual([note["mark"] for note in notes], ["!", "!"])  # nothing the model writes is run
        self.assertEqual(len(self.started), 2)
        self.assertIn("I could not find", notes[0]["text"])

    def test_an_address_is_opened_only_if_the_person_typed_it(self):
        notes = self.run_actions("open kun.uz please", open=["kun.uz"])
        self.assertEqual((self.cat.opened, notes[0]["text"]), (["https://kun.uz"], "Opened: https://kun.uz"))
        notes = self.run_actions("open the news", open=["evil.example.com"])
        self.assertEqual(len(self.cat.opened), 1)
        self.assertEqual(notes[0]["mark"], "!")

    def test_a_search_opens_the_browser(self):
        notes = self.run_actions(search="flights to Tashkent & back")
        self.assertEqual(self.cat.opened, ["https://www.google.com/search?q=flights+to+Tashkent+%26+back"])
        self.assertEqual(notes[0]["text"], "Searched the web for: flights to Tashkent & back")

    def test_remembering_and_forgetting(self):
        notes = self.run_actions(remember=["The user's manager is Aziz."])
        self.assertEqual(notes[0]["text"], "I will remember: The user's manager is Aziz.")
        note = self.store.notes()[0]
        self.assertEqual(self.run_actions(remember=["the user's manager is aziz."]), [])  # known already: nothing to say
        notes = self.run_actions(forget=[note["id"]])
        self.assertEqual((notes[0]["text"], self.store.notes()), ("Forgotten: The user's manager is Aziz.", []))
        notes[0]["undo"]()
        self.assertEqual(self.store.notes(), [note])

    def test_what_is_switched_off_is_not_done_whatever_the_model_says(self):
        self.cat.settings.update(ai_may_edit=False, ai_may_open=False, ai_memory=False, ai_may_timer=False, ai_may_add=False)
        notes = self.run_actions(done=[self.report], remove=[self.bank], open=["excel"], search="x", remember=["y"], focus_minutes=25, reminders=[{"text": "Z", "when": ""}], goals=["g"])
        self.assertEqual(notes, [])
        self.assertEqual(sorted(self.open_texts()), ["Call the bank", "Send the report"])
        self.assertEqual((self.started, self.cat.opened, self.store.notes(), self.cat.focusing), ([], [], [], False))

    def test_asking_first(self):
        self.cat.settings["ai_ask_first"] = True
        notes = self.run_actions(done=[self.report], open=["excel"], reminders=[{"text": "Buy milk", "when": ""}], suggestions=["Khruangbin"])
        self.assertEqual([(note.get("mark"), note["text"]) for note in notes], [
            ("?", "Add to your list: Buy milk?"), ("?", "Tick off: Send the report?"), ("?", "Open Excel?"), (None, "Look these up:"),
        ])
        self.assertEqual((sorted(self.open_texts()), self.started), (["Call the bank", "Send the report"], []))  # nothing has happened yet
        done = notes[1]["do"]()
        self.assertEqual((done["text"], self.open_texts()), ("Finished: Send the report", ["Call the bank"]))
        done["undo"]()
        self.assertEqual(notes[2]["do"]()["text"], "Opened: Excel")
        self.assertEqual(self.started, [r"C:\menu\Excel.lnk"])

    def test_the_older_actions_still_work(self):
        notes = self.run_actions("start a 40 minute focus timer", reminders=[{"text": "Call mom", "when": "tomorrow 09:00"}], focus_minutes=40, suggestions=["Khruangbin"])
        self.assertTrue(notes[0]["text"].startswith("Reminder set: Call mom ("))
        self.assertEqual((notes[1]["text"], self.cat.focus_len, self.cat.focusing), ("Focus timer started: 40 min", 40, True))
        notes[1]["undo"]()
        self.assertFalse(self.cat.focusing)
        notes[0]["undo"]()
        self.assertNotIn("Call mom", self.open_texts())
        self.assertEqual(notes[2]["links"][0][0], "Khruangbin")
        notes = self.cat.run_ai_actions([{"do": "unsure"}], None)
        self.assertEqual((notes[0]["mark"], notes[0]["buttons"][0][0]), ("!", "Open tasks"))

    def test_an_offer_waits_for_its_button(self):
        notes = self.cat.run_ai_actions([{"do": "offer", "task": self.report}], None)
        self.assertEqual([(note["mark"], note["text"]) for note in notes], [("?", "Tick off: Send the report?")])
        self.assertEqual(sorted(self.open_texts()), ["Call the bank", "Send the report"])  # asked, not done
        self.assertEqual(notes[0]["do"]()["text"], "Finished: Send the report")
        self.assertEqual(self.open_texts(), ["Call the bank"])
        self.cat.settings["ai_may_edit"] = False  # with finishing tasks switched off there is nothing to offer
        self.assertEqual(self.cat.run_ai_actions([{"do": "offer", "task": self.bank}], None), [])

    def test_one_morning_question_not_two(self):
        cat = self.cat
        nine = dt.datetime.combine(dt.date.today(), dt.time(9, 0)).timestamp()
        cat.day_started = nine - 600
        self.assertTrue(cat.plan_due(nine))
        self.assertEqual(cat.offers, [("plan", "Good morning! Shall I plan your day?", "Plan my day")])
        self.assertFalse(cat.plan_due(nine + 60))  # once a day
        self.assertFalse(cat.goals_due(nine + 60))  # and the goals question stays away that day
        cat.said, cat.offers = set(), []
        cat.ai.state = "missing"  # no AI to make a plan: the question about the three goals is asked as before
        self.assertFalse(cat.plan_due(nine))
        self.assertTrue(cat.goals_due(nine))
        self.assertEqual(cat.offers[0][0], "goals")
        cat.said, cat.offers, cat.ai.state = set(), [], "ready"
        cat.settings["plan_morning"] = False
        self.assertFalse(cat.plan_due(nine))
        cat.settings["plan_morning"] = True
        evening = dt.datetime.combine(dt.date.today(), dt.time(19, 0)).timestamp()
        self.assertFalse(cat.plan_due(evening))


class OpenByNameTest(unittest.TestCase):
    PLACES = {
        "excel": {"place": "excel", "name": "Excel", "category": "office", "path": r"C:\Office\EXCEL.EXE", "last_seen": 50},
        "code": {"place": "code", "name": "VS Code", "category": "code", "path": r"C:\Code\Code.exe", "last_seen": 90},
        "site:youtube": {"place": "site:youtube", "name": "YouTube", "category": "media", "path": r"C:\chrome.exe", "last_seen": 80},
        "shellhost": {"place": "shellhost", "name": "Shell Host", "category": "system", "path": r"C:\Windows\shellhost.exe", "last_seen": 99},
    }
    LINKS = {"google chrome": ("Google Chrome", r"C:\menu\Google Chrome.lnk"), "word": ("Word", r"C:\menu\Word.lnk"), "wordpad": ("WordPad", r"C:\menu\WordPad.lnk")}

    def find(self, name: str):
        return apps.find_target(name, self.PLACES, self.LINKS)

    def test_where_a_name_leads(self):
        self.assertEqual(self.find("excel"), apps.Target("Excel", "place", "excel"))  # a program the cat has seen
        self.assertEqual(self.find("Microsoft Excel").what, "excel")
        self.assertEqual(self.find("vs code").what, "code")
        self.assertEqual(self.find("chrome"), apps.Target("Google Chrome", "shortcut", r"C:\menu\Google Chrome.lnk"))  # the Start menu
        self.assertEqual(self.find("word").name, "Word")  # not WordPad
        self.assertEqual(self.find("YouTube"), apps.Target("YouTube", "site", "https://www.youtube.com"))
        self.assertEqual(self.find("gmail").what, "https://mail.google.com")
        self.assertEqual(self.find("Блокнот"), apps.Target("Notepad", "tool", "notepad.exe"))
        self.assertEqual(self.find("sozlamalar").what, "ms-settings:")
        for nothing in ("", "   ", "shell host", "definitely not installed", r"C:\Windows\System32\cmd.exe", "cmd.exe /c del *", "powershell -c x"):
            self.assertIsNone(self.find(nothing), nothing)

    def test_the_start_menu_is_read_without_its_uninstallers(self):
        with tempfile.TemporaryDirectory() as folder:
            menu = Path(folder) / "Programs"
            (menu / "Tools").mkdir(parents=True)
            for name in ("Excel.lnk", "Tools/Paint Pro.lnk", "Tools/Uninstall Paint Pro.lnk", "Paint Pro Help.lnk", "notes.txt", "Site.url"):
                (menu / name).write_bytes(b"")
            found = apps.shortcuts([str(menu)], fresh=True)
            self.assertEqual(sorted(found), ["excel", "paint pro"])
            self.assertEqual(found["paint pro"][0], "Paint Pro")

    def test_an_address_must_be_the_persons_own(self):
        self.assertEqual(apps.typed_address("kun.uz", "open kun.uz please"), "https://kun.uz")
        self.assertEqual(apps.typed_address("https://www.kun.uz/news/2026", "open kun.uz/news/2026"), "https://kun.uz/news/2026")
        self.assertEqual(apps.typed_address("kun.uz/other", "open kun.uz"), "https://kun.uz")  # the part they did not type is left off
        self.assertEqual(apps.typed_address("evil.example.com", "open the news"), "")
        self.assertEqual(apps.typed_address("Excel", "open Excel"), "")

    def test_what_the_ai_is_told_it_can_open(self):
        self.assertEqual(apps.openable(self.PLACES), ["VS Code", "YouTube", "Excel"])  # most recent first, nothing of Windows' own


class FakeEngine:
    """An engine that has models or not, answers at once, and counts what it is asked."""

    process = None
    source = llm.ENGINE

    def __init__(self, have=()):
        self.have, self.asked, self.warmed, self.stops = set(have), [], [], 0
        self.gate = threading.Event()
        self.keep_loaded = None

    def installed(self) -> bool:
        return bool(self.have)

    def ready(self, model: str) -> bool:
        return model in self.have

    def unfinished(self) -> bool:
        return False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stops += 1

    def warm(self, model: str) -> None:
        self.warmed.append(model)

    def chat(self, model, messages, schema=None, on_text=None, cancel=None, options=None, on_again=None, tries=2) -> str:
        self.asked.append((model, messages, options))
        raw = answer(reply="from this computer")
        if on_text:
            on_text(raw)
        return raw

    def setup(self, model, report, cancel) -> None:
        report("model", 1, 2)
        self.gate.wait(10)
        if cancel.is_set():
            raise llm.Cancelled()
        self.have.add(model.name)

    def remove(self) -> None:
        self.have.clear()


class Host:
    """As much of the app as the AI controller needs."""

    def __init__(self, store):
        self.store, self.settings, self.inbox = store, store.settings, queue.Queue()
        self.ready_said, self.acted = 0, []

    def run_ai_actions(self, actions, turn=None) -> list:
        self.acted.append(actions)
        return []

    def on_ai_ready(self) -> None:
        self.ready_said += 1

    def on_ai_failed(self, error) -> None:
        pass


class BrainsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pretend)
        cls.address = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.sleep, cloud.time.sleep = cloud.time.sleep, lambda seconds: None

    @classmethod
    def tearDownClass(cls):
        cloud.time.sleep = cls.sleep
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Pretend.seen, Pretend.answer_with, Pretend.message, Pretend.no_json_mode = [], [], "nope", False
        Pretend.models = ["b-model", "models/a-model"]
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.host = Host(self.store)
        self.engine = FakeEngine()
        self.ai = AI(self.host, self.engine)
        self.heard = []
        self.ai.listeners.append(lambda what, payload: self.heard.append((what, payload)))

    def tearDown(self):
        self.engine.gate.set()
        self.store.close()
        self.folder.cleanup()

    def online(self, model: str = "some-model", address: str = "", source: str = "online") -> None:
        self.host.settings.update(ai_source=source, ai_service="other", ai_address=address or self.address, ai_online_model=model, ai_key=cloud.lock("sk-test-not-a-real-key"))
        self.ai.settle()

    def pump(self, until, seconds: float = 8.0) -> None:
        """Hand the worker threads' messages over, as the app's own loop does."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                kind, payload = self.host.inbox.get(timeout=0.05)
            except queue.Empty:
                continue
            self.ai.handle(*payload)
            if until():
                return
        self.fail(f"waited in vain; heard {[what for what, _ in self.heard]}")

    def said(self, what: str):
        return [payload for heard, payload in self.heard if heard == what]

    def test_the_state_says_whether_the_chosen_brain_can_answer(self):
        self.assertEqual((self.ai.state, self.ai.local), ("missing", None))
        self.engine.have.add("gemma3:4b")
        self.ai.settle()
        self.assertEqual((self.ai.state, self.ai.local.name, self.ai.model_name), ("ready", "gemma3:4b", "gemma3:4b"))
        self.host.settings["ai_model"] = "better"  # chosen, not downloaded: the model that is here stands in
        self.ai.settle()
        self.assertEqual((self.ai.state, self.ai.local.name, self.ai.model.name), ("ready", "gemma3:4b", "gemma3:12b"))
        self.host.settings.update(ai_source="online", ai_service="claude")
        self.ai.settle()
        self.assertEqual(self.ai.state, "nokey")
        self.online()
        self.assertEqual((self.ai.state, self.ai.model_name), ("ready", "some-model"))
        self.host.settings["ai_keep_ready"] = True
        self.ai.settle()
        self.assertEqual(self.engine.keep_loaded, -1)
        self.host.settings["ai_keep_ready"] = False
        self.ai.settle()
        self.assertEqual(self.engine.keep_loaded, llm.KEEP_LOADED)

    def test_a_key_saved_under_the_wrong_service_finds_its_own(self):
        settings = self.host.settings
        settings.update(ai_source="online", ai_service="openai", ai_online_model="gpt-x", ai_key=cloud.lock("sk-ant-test-not-a-real-key"))
        moved = AI(self.host, self.engine)  # as at the first start after the update
        self.assertEqual((moved.moved_to, settings["ai_service"], settings["ai_online_model"]), ("Claude (Anthropic)", "claude", ""))
        self.assertEqual((moved.state, moved.model_name), ("ready", "claude-opus-5-5"))
        self.assertEqual(json.loads(self.store.settings_path.read_text(encoding="utf-8"))["ai_service"], "claude")
        self.assertEqual(AI(self.host, self.engine).moved_to, "")  # once
        settings.update(ai_service="other", ai_address=self.address)  # an address typed by hand is left alone
        self.assertEqual((AI(self.host, self.engine).moved_to, settings["ai_service"]), ("", "other"))
        settings.update(ai_service="deepseek", ai_address="", ai_key=cloud.lock("sk-plain-key"))  # a key that does not say whose it is
        self.assertEqual((AI(self.host, self.engine).moved_to, settings["ai_service"]), ("", "deepseek"))

    def test_the_online_ai_answers_while_the_offline_one_is_fetched(self):
        self.online()
        self.ai.setup()
        self.assertTrue(self.ai.fetching)
        self.assertEqual(self.ai.state, "ready")  # the download does not stand in the online AI's way
        self.assertEqual(self.store.get(AI.WANTED), "standard")
        self.assertTrue(self.ai.ask("hello there, how are you?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("answer"))
        self.assertEqual(self.said("answer")[0][0], "Hello there")
        self.assertTrue(self.ai.fetching)
        self.ai.rest(time.time() + 86400)
        self.assertEqual(self.engine.stops, 0)  # an engine that is fetching a model is not put to rest
        self.engine.gate.set()
        self.pump(lambda: not self.ai.fetching)
        self.assertEqual((self.ai.local.name, self.host.ready_said, self.store.get(AI.WANTED)), ("gemma3:4b", 1, False))

    def test_without_an_ai_here_the_first_download_is_the_state(self):
        self.ai.setup()
        self.assertEqual(self.ai.state, "setup")
        self.pump(lambda: self.said("progress"))
        self.assertEqual((self.ai.stage, self.ai.done, self.ai.total), ("model", 1, 2))
        self.ai.stop_setup()
        self.engine.gate.set()
        self.pump(lambda: not self.ai.fetching)
        self.assertEqual((self.ai.state, self.store.get(AI.WANTED)), ("missing", False))

    def test_when_the_online_ai_is_down_the_one_on_this_computer_answers(self):
        self.engine.have.add("gemma3:4b")
        self.online(address="http://127.0.0.1:1", source="both")  # nobody answers there
        self.assertTrue(self.ai.ask("Эртага соат 10 да эслат", lambda local: ("LOCAL" if local else "ONLINE", "NOW"), tasks={4: "Send the report"}))
        self.pump(lambda: self.said("answer"))
        reply, notes = self.said("answer")[0]
        self.assertEqual(reply, "from this computer")
        self.assertEqual(notes[0]["mark"], "!")
        self.assertIn("The online AI did not answer, so my brain on this computer did.", notes[0]["text"])
        self.assertIn("No connection to the online service", notes[0]["text"])
        self.assertEqual(len(self.said("switched")), 1)
        model, messages, options = self.engine.asked[0]
        self.assertEqual((model, messages[0]["content"], options), ("gemma3:4b", "LOCAL", {"num_predict": 700}))
        self.assertIn("Ertaga soat 10 da eslat", messages[-1]["content"])  # the small model gets Uzbek in Latin letters
        self.assertTrue(self.ai.asked.careful and self.ai.asked.tasks == {4: "Send the report"})
        self.assertEqual([row["role"] for row in self.store.talk()], ["user", "assistant"])  # kept for after a restart
        self.assertFalse(self.ai.busy)
        self.assertIsNotNone(self.ai.timing)

    def test_a_wrong_key_is_said_when_nothing_can_stand_in(self):
        self.online()
        Pretend.answer_with, Pretend.message = [401], "invalid key"
        self.assertTrue(self.ai.ask("hello there, how are you?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("error"))
        self.assertEqual(self.said("error"), ["The service did not accept the key. Is it a key for this service, and typed in full?"])
        self.assertFalse(self.ai.busy)
        self.engine.have.add("gemma3:4b")  # ... and with "online only" chosen it is said too, whatever is on this computer
        self.ai.settle()
        Pretend.answer_with = [401]
        self.heard.clear()
        self.assertTrue(self.ai.ask("hello there, how are you?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("error"))
        self.assertEqual(self.engine.asked, [])

    def test_the_test_needs_no_model_to_be_chosen_first(self):
        self.online(model="")
        self.assertEqual(self.ai.state, "nokey")  # no model yet
        self.ai.test()
        self.pump(lambda: self.said("tested"))
        ok, result = self.said("tested")[0]
        self.assertTrue(ok)
        self.assertEqual((result["model"], self.host.settings["ai_online_model"]), ("a-model", "a-model"))  # picked from the service's own list, and kept
        self.assertEqual((self.ai.state, self.ai.found["other"]), ("ready", ["a-model", "b-model"]))
        self.assertGreaterEqual(result["seconds"], 0)
        self.assertEqual(Pretend.seen[-1][3]["model"], "a-model")

    def test_the_list_of_models_arrives_and_one_is_picked(self):
        self.online(model="")
        self.ai.list_models()
        self.pump(lambda: self.said("models"))
        ok, result = self.said("models")[0]
        self.assertEqual((ok, result["names"], result["model"], self.ai.state), (True, ["a-model", "b-model"], "a-model", "ready"))
        self.host.settings["ai_online_model"] = "b-model"  # a model the person chose is left alone
        self.heard.clear()
        self.ai.list_models()
        self.pump(lambda: self.said("models"))
        self.assertEqual((self.said("models")[0][1]["model"], self.host.settings["ai_online_model"]), ("", "b-model"))

    def test_a_key_without_a_model_finds_one_by_itself(self):
        self.online(model="")
        self.assertEqual(self.ai.state, "nokey")
        self.ai.find_model()
        self.pump(lambda: self.said("models"))
        self.assertEqual((self.ai.state, self.host.settings["ai_online_model"]), ("ready", "a-model"))
        asked = len(Pretend.seen)
        self.ai.find_model()  # a model is there: nothing more is asked
        self.host.settings["ai_online_model"] = ""
        self.ai.settle()
        self.ai.find_model()  # ... and not again and again within the same half minute
        time.sleep(0.2)
        self.assertEqual(len(Pretend.seen), asked)
        self.host.settings.update(ai_source="offline")
        self.ai.last_find = 0.0
        self.ai.find_model()  # the offline AI answers: the service is left alone
        time.sleep(0.2)
        self.assertEqual(len(Pretend.seen), asked)

    def test_what_is_wrong_with_the_service_is_said(self):
        self.online(model="")
        Pretend.models = []
        self.ai.test()
        self.pump(lambda: self.said("tested"))
        self.assertEqual(self.said("tested")[0], (False, "The service listed no models to talk to."))
        Pretend.answer_with, Pretend.message = [401], "bad key"
        self.heard.clear()
        self.ai.list_models()
        self.pump(lambda: self.said("models"))
        self.assertEqual(self.said("models")[0], (False, "The service did not accept the key. Is it a key for this service, and typed in full?"))
        self.online(model="m", address="http://127.0.0.1:1")
        self.heard.clear()
        self.ai.test()
        self.pump(lambda: self.said("tested"))
        self.assertEqual(self.said("tested")[0], (False, "No connection to the online service. Is the internet working, and is the address right?"))

    def test_the_offline_ai_can_be_tested_too(self):
        self.engine.have.add("gemma3:1b")
        self.host.settings["ai_model"] = "small"
        self.ai.settle()
        self.ai.test()
        self.pump(lambda: self.said("tested"))
        ok, result = self.said("tested")[0]
        self.assertEqual((ok, result["model"], self.engine.asked[0][2]), (True, "gemma3:1b", {"num_predict": 8}))

    def test_the_model_is_loaded_when_someone_is_about_to_ask(self):
        self.ai.warm()
        self.assertEqual(self.engine.warmed, [])  # nothing here to load
        self.engine.have.add("gemma3:4b")
        self.ai.settle()
        self.ai.warm()
        end = time.monotonic() + 5
        while self.ai.warming and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(self.engine.warmed, ["gemma3:4b"])
        self.ai.warm()  # opening the box again a moment later asks for nothing
        time.sleep(0.05)
        self.assertEqual(len(self.engine.warmed), 1)
        self.online()
        self.ai.last_warm = 0
        self.ai.warm()  # the online AI answers: nothing to load
        self.assertEqual(len(self.engine.warmed), 1)

    def test_the_engine_rests_unless_it_is_to_stay_ready(self):
        self.engine.have.add("gemma3:4b")
        self.engine.process = object()
        self.ai.settle()
        self.ai.last_used = 1000.0
        self.host.settings["ai_keep_ready"] = True
        self.ai.rest(1000.0 + 86400)
        self.assertEqual(self.engine.stops, 0)
        self.host.settings["ai_keep_ready"] = False
        self.ai.rest(1000.0 + 60)
        self.assertEqual(self.engine.stops, 0)
        self.ai.rest(1000.0 + 31 * 60)
        self.assertEqual(self.engine.stops, 1)

    def test_the_conversation_is_taken_up_again_after_a_restart(self):
        self.engine.have.add("gemma3:4b")
        self.ai.settle()
        self.assertTrue(self.ai.ask("what is on my list today?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("answer"))
        again = AI(self.host, self.engine)
        self.assertEqual([message["role"] for _, message in again.talk.history], ["user", "assistant"])
        self.assertEqual(again.talk.history[0][1]["content"], "what is on my list today?")
        self.ai.clear_talk()
        self.assertEqual((self.store.talk(), self.ai.talk.history), ([], []))
        self.host.settings["ai_keep_talk"] = False  # switched off: nothing is written down
        self.heard.clear()
        self.assertTrue(self.ai.ask("and tomorrow, what then?", ("LASTING", "NOW")))
        self.pump(lambda: self.said("answer"))
        self.assertEqual(self.store.talk(), [])
        self.assertEqual(len(self.ai.talk.history), 2)  # it is still known while the app runs


if __name__ == "__main__":
    unittest.main()
