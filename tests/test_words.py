"""The interface languages: every text has a translation, placeholders survive, and the
times people type in Russian and Uzbek are understood.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import strings  # noqa: E402  (tools/strings.py)

from workcat import i18n, tasks  # noqa: E402
from workcat.i18n import T  # noqa: E402

# Names that stay in Latin letters in every language.
KEPT = ("YouTube", "Spotify", "Excel", "Gmail", "GitHub", "Windows + H", "Microsoft", "Open-Meteo", "°C", "Windows", "engine.log", "OpenAI", "Enter", "Esc", "Backspace", "Opus", "Sonnet", "Haiku")
NOW = dt.datetime(2026, 11, 12, 10, 0)  # a Thursday


def table(code: str) -> dict:
    return json.loads((ROOT / "workcat" / "lang" / f"{code}.json").read_text(encoding="utf-8"))


def bare(text: str) -> str:
    """A translation without its {placeholders} and the names that stay as they are."""
    text = re.sub(r"\{[^}]*\}", "", text)
    for name in KEPT:
        text = text.replace(name, "")
    return text


class LanguageFilesTest(unittest.TestCase):
    def tearDown(self):
        i18n.load("en")

    def test_every_text_is_translated_with_the_same_placeholders(self):
        for code in ("ru", "uz"):
            with self.subTest(language=code):
                self.assertEqual(strings.check(code), dict(missing=[], extra=[], broken=[], empty=[]))

    def test_every_language_offered_has_its_file(self):
        for code in i18n.LANGUAGES:
            if code != "en":
                self.assertTrue((ROOT / "workcat" / "lang" / f"{code}.json").exists(), code)

    def test_translations_are_written_in_cyrillic(self):
        """Uzbek here is the Cyrillic kind: no Latin letters outside names like YouTube."""
        for code in ("ru", "uz"):
            for english, text in table(code).items():
                latin = re.findall(r"[A-Za-z]+", bare(text))
                self.assertEqual(latin, [], f"{code}: {english!r} -> {text!r}")

    def test_uzbek_uses_its_own_letters_not_look_alikes(self):
        """ў қ ғ ҳ are single characters, and no Latin look-alike sits inside a Cyrillic word."""
        text = " ".join(table("uz").values())
        for letter in "ўқғҳ":
            self.assertIn(letter, text)
        self.assertNotIn("̆", text)  # a separate breve: "у" + "̆" instead of "ў"
        self.assertEqual(re.findall(r"[А-яЎўҚқҒғҲҳ][A-Za-z]|[A-Za-z][А-яЎўҚқҒғҲҳ]", bare(text)), [])

    def test_russian_has_no_uzbek_letters_and_the_other_way_round(self):
        self.assertEqual(re.findall(r"[ўқғҳЎҚҒҲ]", " ".join(table("ru").values())), [])
        self.assertEqual(re.findall(r"[ыщЫЩ]", " ".join(table("uz").values())), [])  # letters Uzbek does not have

    def test_the_time_hints_shown_are_times_the_app_understands(self):
        """Each language's hint quotes three examples; all three must really work."""
        hint = 'Add a time at the end and I will remind you: "at 15:30", "in 20 min", "tomorrow 9:00".'
        for code in ("en", "ru", "uz"):
            i18n.load(code)
            examples = re.findall(r"[«\"]([^»\"]+)[»\"]", T(hint))
            self.assertEqual(len(examples), 3, code)
            for example, wanted in zip(examples, (dt.datetime(2026, 11, 12, 15, 30), dt.datetime(2026, 11, 12, 10, 20), dt.datetime(2026, 11, 13, 9, 0))):
                self.assertEqual(tasks.parse_quick("x " + example, NOW), ("x", wanted), f"{code}: {example}")

    def test_menu_names_quoted_in_sentences_match_the_menu(self):
        """A bubble that says: pick "Ask me" must name the item the way the menu shows it."""
        quoting = (
            ('My AI brain is ready. Pick "Ask me" in my menu and we can talk.', "Ask me"),
            ('I have a new look, moods of my own, and an AI brain that runs only on this PC. Right-click me and pick "Ask me".', "Ask me"),
            ('I have a new look and moods of my own now. Right-click me and try "What should I do now?".', "What should I do now?"),
            ('Turned off. Switch on "Notice what I listen to and watch" in Settings and I will suggest music and videos at the times you usually play them.', "Notice what I listen to and watch"),
            ("Or use an online AI with your own key, or a bigger model: see the AI brain tab.", "AI brain"),
            ("You chose an online service as my AI brain. Give me its key in the AI brain tab, and we can talk.", "AI brain"),
            ("The service does not know this model, or its address is wrong. Please check both in the AI brain tab.", "AI brain"),
            ("Paste the key below and press Save. Until then I cannot answer questions.", "Save"),
            ("First paste your key and press Save.", "Save"),
            ('Off: I do it at once and show Undo. On: I show a "Do it" button and wait for you.', "Do it"),
            ('Off: I do it at once and show Undo. On: I show a "Do it" button and wait for you.', "Undo"),
            ('"I sent the report", "move the bank call to tomorrow at 10", "open Excel": I do it, say what I did, and show Undo.', "Undo"),
        )
        for code in ("ru", "uz"):
            words = table(code)
            for sentence, item in quoting:
                self.assertIn("«" + words[item] + "»", words[sentence], f"{code}: {item}")


class TranslatingTest(unittest.TestCase):
    def tearDown(self):
        i18n.load("en")

    def test_english_is_the_text_itself(self):
        i18n.load("en")
        self.assertEqual(T("Open tasks"), "Open tasks")
        self.assertEqual(T("{n} min", n=5), "5 min")

    def test_russian_and_uzbek(self):
        i18n.load("ru")
        self.assertEqual(T("Open tasks"), "Открыть задачи")
        self.assertEqual(T("{n} min", n=5), "5 мин")
        self.assertEqual(i18n.duration(3900), "1 ч 05 мин")
        i18n.load("uz")
        self.assertEqual(T("Open tasks"), "Вазифаларни очиш")
        self.assertEqual(i18n.duration(3900), "1 соат 05 дақ")
        self.assertEqual(i18n.duration(20), "бир дақиқадан кам")

    def test_an_unknown_language_or_text_falls_back_to_english(self):
        i18n.load("xx")
        self.assertEqual(T("Open tasks"), "Open tasks")
        i18n.load("ru")
        self.assertEqual(T("A text nobody translated {n}", n=2), "A text nobody translated 2")

    def test_a_translation_with_a_wrong_placeholder_cannot_break_the_app(self):
        i18n.load("ru")
        i18n._table["{n} min"] = "{minutes} мин"
        self.assertEqual(T("{n} min", n=5), "5 min")

    def test_plain_gives_english_for_the_ai(self):
        i18n.load("uz")
        with i18n.plain():
            self.assertEqual(T("Open tasks"), "Open tasks")
            self.assertEqual(i18n.duration(3900), "1 h 05 min")
        self.assertEqual(T("Open tasks"), "Вазифаларни очиш")

    def test_task_times_are_labelled_in_the_language(self):
        tomorrow = dt.datetime(2026, 11, 13, 9, 0).timestamp()
        monday = dt.datetime(2026, 11, 16, 9, 0).timestamp()
        past = dt.datetime(2026, 11, 12, 9, 0).timestamp()
        i18n.load("ru")
        self.assertEqual(tasks.due_label(tomorrow, NOW), "завтра 09:00")
        self.assertEqual(tasks.due_label(monday, NOW), "Пн 09:00")
        self.assertEqual(tasks.due_label(past, NOW), "просрочено")
        i18n.load("uz")
        self.assertEqual(tasks.due_label(tomorrow, NOW), "эртага 09:00")
        self.assertEqual(tasks.due_label(monday, NOW), "Ду 09:00")
        self.assertEqual(tasks.due_label(past, NOW), "кечикди")

    def test_moods_and_categories_come_out_translated(self):
        from workcat import apps, lines, mood

        i18n.load("uz")
        self.assertEqual(T(mood.MOOD_WORDS["happy"]), "Хурсанд")
        self.assertEqual(T(apps.CATEGORY_NAMES["code"]), "Дастурлаш")
        self.assertIn("Мурка", lines.greeting(9, "Мурка") + lines.greeting(9, "Мурка") + "Мурка")
        self.assertTrue(re.search(r"[А-яЎўҚқҒғҲҳ]", lines.chat("code")))
        self.assertTrue(re.search(r"[А-яЎўҚқҒғҲҳ]", lines.purr()))
        self.assertTrue(re.search(r"[А-яЎўҚқҒғҲҳ]", lines.job_title("code")))


class TimesInOtherLanguagesTest(unittest.TestCase):
    def read(self, text):
        return tasks.parse_quick(text, NOW)

    def test_russian(self):
        self.assertEqual(self.read("Позвонить в банк в 15:30"), ("Позвонить в банк", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Размяться через 20 мин"), ("Размяться", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Размяться через 20 минут"), ("Размяться", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Обед через 2 часа"), ("Обед", dt.datetime(2026, 11, 12, 12, 0)))
        self.assertEqual(self.read("Обед через 1 час"), ("Обед", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Отправить отчёт завтра 9:00"), ("Отправить отчёт", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Отправить отчёт завтра в 9"), ("Отправить отчёт", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Отправить отчёт завтра"), ("Отправить отчёт", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Встреча в 9:00"), ("Встреча", dt.datetime(2026, 11, 13, 9, 0)))  # already past today
        self.assertEqual(self.read("Обед через час"), ("Обед", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Обед через полчаса"), ("Обед", dt.datetime(2026, 11, 12, 10, 30)))
        self.assertEqual(self.read("Позвонить маме в 5 вечера"), ("Позвонить маме", dt.datetime(2026, 11, 12, 17, 0)))
        self.assertEqual(self.read("Позвонить маме в 5:30 вечера"), ("Позвонить маме", dt.datetime(2026, 11, 12, 17, 30)))
        self.assertEqual(self.read("Планёрка в 11 часов"), ("Планёрка", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Планёрка завтра в 9 утра"), ("Планёрка", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Спорт завтра в 7 часов вечера"), ("Спорт", dt.datetime(2026, 11, 13, 19, 0)))
        self.assertEqual(self.read("Встреча в 15.30"), ("Встреча", dt.datetime(2026, 11, 12, 15, 30)))

    def test_uzbek_in_cyrillic(self):
        self.assertEqual(self.read("Мажлис соат 11 да"), ("Мажлис", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Онамга қўнғироқ кечқурун соат 5 да"), ("Онамга қўнғироқ", dt.datetime(2026, 11, 12, 17, 0)))
        self.assertEqual(self.read("Онамга қўнғироқ кечқурун соат 5:30 да"), ("Онамга қўнғироқ", dt.datetime(2026, 11, 12, 17, 30)))
        self.assertEqual(self.read("Тушлик ярим соатдан кейин"), ("Тушлик", dt.datetime(2026, 11, 12, 10, 30)))
        self.assertEqual(self.read("Тушлик бир соатдан кейин"), ("Тушлик", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Спорт эртага кечқурун соат 7 да"), ("Спорт", dt.datetime(2026, 11, 13, 19, 0)))
        self.assertEqual(self.read("Мажлис 15.30 да"), ("Мажлис", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Банкка қўнғироқ 15:30 да"), ("Банкка қўнғироқ", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Банкка қўнғироқ соат 15:30 да"), ("Банкка қўнғироқ", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Банкка қўнғироқ соат 15:30"), ("Банкка қўнғироқ", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Чигил ёзиш 20 дақиқадан кейин"), ("Чигил ёзиш", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Чигил ёзиш 20 минутдан сўнг"), ("Чигил ёзиш", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Тушлик 2 соатдан кейин"), ("Тушлик", dt.datetime(2026, 11, 12, 12, 0)))
        self.assertEqual(self.read("Ҳисобот юбориш эртага 9:00"), ("Ҳисобот юбориш", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Ҳисобот юбориш эртага соат 9:00 да"), ("Ҳисобот юбориш", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Ҳисобот юбориш эртага"), ("Ҳисобот юбориш", dt.datetime(2026, 11, 13, 9, 0)))

    def test_uzbek_in_latin(self):
        self.assertEqual(self.read("Bankka qo'ng'iroq 15:30 da"), ("Bankka qo'ng'iroq", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Chigil yozish 20 daqiqadan keyin"), ("Chigil yozish", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Tushlik 2 soatdan so'ng"), ("Tushlik", dt.datetime(2026, 11, 12, 12, 0)))
        self.assertEqual(self.read("Tushlik 2 soatdan so‘ng"), ("Tushlik", dt.datetime(2026, 11, 12, 12, 0)))  # the other apostrophe
        self.assertEqual(self.read("Hisobot yuborish ertaga soat 9:00 da"), ("Hisobot yuborish", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Majlis kechqurun soat 5 da"), ("Majlis", dt.datetime(2026, 11, 12, 17, 0)))
        self.assertEqual(self.read("Tushlik yarim soatdan keyin"), ("Tushlik", dt.datetime(2026, 11, 12, 10, 30)))

    def test_english_still_reads_as_before(self):
        self.assertEqual(self.read("Call the bank at 15:30"), ("Call the bank", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Call the bank 15:30"), ("Call the bank", dt.datetime(2026, 11, 12, 15, 30)))
        self.assertEqual(self.read("Stretch in 20 min"), ("Stretch", dt.datetime(2026, 11, 12, 10, 20)))
        self.assertEqual(self.read("Lunch in 2 hours"), ("Lunch", dt.datetime(2026, 11, 12, 12, 0)))
        self.assertEqual(self.read("Lunch in an hour"), ("Lunch", dt.datetime(2026, 11, 12, 11, 0)))
        self.assertEqual(self.read("Lunch in half an hour"), ("Lunch", dt.datetime(2026, 11, 12, 10, 30)))
        self.assertEqual(self.read("Stand-up at 9am"), ("Stand-up", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Dinner at 7 pm"), ("Dinner", dt.datetime(2026, 11, 12, 19, 0)))
        self.assertEqual(self.read("Dinner at 7.30pm"), ("Dinner", dt.datetime(2026, 11, 12, 19, 30)))
        self.assertEqual(self.read("Send the report tomorrow 9:00"), ("Send the report", dt.datetime(2026, 11, 13, 9, 0)))
        self.assertEqual(self.read("Send the report tomorrow"), ("Send the report", dt.datetime(2026, 11, 13, 9, 0)))

    def test_words_that_only_look_like_times_are_left_alone(self):
        self.assertEqual(self.read("Купить 2 билета"), ("Купить 2 билета", None))
        self.assertEqual(self.read("Версия 3.10"), ("Версия 3.10", None))
        self.assertEqual(self.read("Update to version 3.10"), ("Update to version 3.10", None))
        self.assertEqual(self.read("Китоб ўқиш"), ("Китоб ўқиш", None))
        self.assertEqual(self.read("Уйда 2 соат ишлаш"), ("Уйда 2 соат ишлаш", None))
        self.assertEqual(self.read("Зайти в 5 магазинов"), ("Зайти в 5 магазинов", None))
        self.assertEqual(self.read("Сходить в 2"), ("Сходить в 2", None))  # the hour alone needs a word that says so
        self.assertEqual(self.read("Meet at 25:99"), ("Meet at 25:99", None))  # not a time of day


if __name__ == "__main__":
    unittest.main()
