"""Uzbek between its two alphabets.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workcat import translit  # noqa: E402
from workcat.translit import to_cyrillic, to_latin  # noqa: E402

# Words that must come out the same in both directions.
BOTH_WAYS = (
    ("салом", "salom"), ("раҳмат", "rahmat"), ("ўзбек", "o'zbek"), ("қўнғироқ", "qo'ng'iroq"), ("ғалаба", "g'alaba"),
    ("шаҳар", "shahar"), ("чой", "choy"), ("яхши", "yaxshi"), ("ёрдам", "yordam"), ("юлдуз", "yulduz"), ("ер", "yer"),
    ("етти", "yetti"), ("кейин", "keyin"), ("эртага", "ertaga"), ("эслатма", "eslatma"), ("маъно", "ma'no"),
    ("эътибор", "e'tibor"), ("санъат", "san'at"), ("йўқ", "yo'q"), ("йўл", "yo'l"), ("тайёр", "tayyor"), ("дунё", "dunyo"),
    ("бўйича", "bo'yicha"), ("қиляпман", "qilyapman"), ("ўйлаяпман", "o'ylayapman"), ("тоғ", "tog'"), ("боғ", "bog'"),
    ("мўъжиза", "mo''jiza"), ("поезд", "poyezd"), ("аёл", "ayol"), ("буюк", "buyuk"), ("қуёш", "quyosh"),
    ("информация", "informatsiya"), ("функция", "funksiya"), ("версия", "versiya"), ("миллий", "milliy"),
    ("деярли", "deyarli"), ("тўғри", "to'g'ri"), ("минг", "ming"), ("кўнгил", "ko'ngil"), ("ҳисобот", "hisobot"),
    ("вазифа", "vazifa"), ("танаффус", "tanaffus"), ("дақиқа", "daqiqa"), ("жуда", "juda"), ("хайр", "xayr"),
    ("уй", "uy"), ("ойна", "oyna"), ("қийин", "qiyin"), ("мажлис", "majlis"), ("тушлик", "tushlik"),
    # capitals
    ("Тошкент", "Toshkent"), ("Ўзбекистон", "O'zbekiston"), ("Шанба", "Shanba"), ("Чой", "Choy"), ("Ёрдам", "Yordam"),
    ("Ер", "Yer"), ("Ғалаба", "G'alaba"), ("Исҳоқ", "Is'hoq"), ("Эртага", "Ertaga"), ("Юлдуз", "Yulduz"), ("Яхши", "Yaxshi"),
    ("ҲИСОБОТ", "HISOBOT"), ("ЧОЙ", "CHOY"), ("ШАҲАР", "SHAHAR"), ("ЎЗБЕК", "O'ZBEK"),
)
SENTENCES = (
    ("Эртага соат 10 да ҳисобот юборишни эслатиб қўй", "Ertaga soat 10 da hisobot yuborishni eslatib qo'y"),
    ("Салом! Куним қандай ўтяпти?", "Salom! Kunim qanday o'tyapti?"),
    ("Диққатни жамлаш учун мусиқа тавсия қил.", "Diqqatni jamlash uchun musiqa tavsiya qil."),
    ("Ҳозир нима қилай? 25 дақиқа фокус, кейин 5 дақиқа танаффус.", "Hozir nima qilay? 25 daqiqa fokus, keyin 5 daqiqa tanaffus."),
    ("Сиз 72 дақиқадан бери тўхтовсиз ишлаяпсиз — бироз чигил ёзиб оласизми?", "Siz 72 daqiqadan beri to'xtovsiz ishlayapsiz — biroz chigil yozib olasizmi?"),
)


class BothWaysTest(unittest.TestCase):
    def test_words(self):
        for cyrillic, latin in BOTH_WAYS:
            with self.subTest(word=cyrillic):
                self.assertEqual(to_latin(cyrillic), latin)
                self.assertEqual(to_cyrillic(latin), cyrillic)

    def test_sentences(self):
        for cyrillic, latin in SENTENCES:
            with self.subTest(sentence=cyrillic):
                self.assertEqual(to_latin(cyrillic), latin)
                self.assertEqual(to_cyrillic(latin), cyrillic)

    def test_the_interface_translation_survives_the_round_trip(self):
        """Every Uzbek text of the app, there and back: a wide net for letters the rules
        get wrong. Borrowed words that lose a soft sign on the way are the only losses."""
        import json
        import re

        table = json.loads((Path(translit.__file__).parent / "lang" / "uz.json").read_text(encoding="utf-8"))
        lost: dict = {}
        for text in table.values():
            for word in re.findall(r"[Ѐ-ӿ]+", text):
                back = to_cyrillic(to_latin(word))
                if back != word:
                    lost[word] = back
        soft = {word for word, back in lost.items() if word.replace("ь", "").replace("ъ", "").lower() == back.replace("ь", "").replace("ъ", "").lower()}
        self.assertEqual({word: back for word, back in lost.items() if word not in soft}, {})
        self.assertLess(len(soft), 12, soft)


class ToLatinTest(unittest.TestCase):
    def test_e_after_a_vowel(self):
        for cyrillic, latin in (("поэзия", "poeziya"), ("дуэт", "duet"), ("аэропорт", "aeroport"), ("клиент", "kliyent"), ("диета", "diyeta")):
            self.assertEqual(to_latin(cyrillic), latin)
            self.assertEqual(to_cyrillic(latin), cyrillic)
        self.assertEqual(to_cyrillic("klient"), "клиент")  # as people also spell it

    def test_letters_that_depend_on_their_place(self):
        self.assertEqual(to_latin("цирк"), "sirk")  # ц is s at the start of a word ...
        self.assertEqual(to_latin("милиция"), "militsiya")  # ... and ts after a vowel
        self.assertEqual(to_latin("объект"), "obyekt")
        self.assertEqual(to_latin("компьютер"), "kompyuter")
        self.assertEqual(to_latin("ателье"), "atelye")
        self.assertEqual(to_latin("сентябрь"), "sentyabr")
        self.assertEqual(to_latin("ёш ер юз яна"), "yosh yer yuz yana")

    def test_what_is_not_uzbek_cyrillic_is_left_alone(self):
        self.assertEqual(to_latin("Excel'ни оч, 15:30 да!"), "Excel'ni och, 15:30 da!")
        self.assertEqual(to_latin("Hello, дунё!"), "Hello, dunyo!")
        self.assertEqual(to_latin(""), "")


class ToCyrillicTest(unittest.TestCase):
    def test_every_sign_people_type_for_the_apostrophe(self):
        self.assertEqual(to_cyrillic("o‘zbek, soʻng, g’alaba, qo`y"), "ўзбек, сўнг, ғалаба, қўй")

    def test_borrowed_words_get_their_spelling_back(self):
        self.assertEqual(to_cyrillic("sirk"), "цирк")
        self.assertEqual(to_cyrillic("Kompyuter"), "Компьютер")
        self.assertEqual(to_cyrillic("kompyuterda"), "компьютерда")
        self.assertEqual(to_cyrillic("Sentabrda film ko'ramiz"), "Сентябрда фильм кўрамиз")
        self.assertEqual(to_cyrillic("konsertga"), "концертга")

    def test_names_are_left_in_latin_letters(self):
        keep = translit.latin_words("Excel, YouTube, VS Code, Lo-Fi Girl")
        self.assertEqual(keep, {"excel", "youtube", "vs", "code", "lo", "fi", "girl"})
        self.assertEqual(to_cyrillic("Excel'ni oching va YouTube'da musiqa qo'ying", keep), "Excel'ни очинг ва YouTube'да мусиқа қўйинг")
        self.assertEqual(to_cyrillic("Excelda ishlang", keep), "Excelда ишланг")
        self.assertEqual(to_cyrillic("VS Code va Lo-Fi Girl", keep), "VS Code ва Lo-Fi Girl")
        self.assertEqual(to_cyrillic("Girlfriend", keep), "Гирлфриенд")  # a name is not kept inside another word

    def test_words_that_cannot_be_uzbek_are_left_alone(self):
        self.assertEqual(to_cyrillic("Windows va music"), "Windows ва music")  # w, and a c without h
        self.assertEqual(to_cyrillic("Салом, dunyo! 15:30"), "Салом, дунё! 15:30")
        self.assertEqual(to_cyrillic("Check the weekly book copy"), "Check the weekly book copy")
        for uzbek in ("choy", "uy", "milliy", "kitob", "sochiq", "tushlik", "qo'shiq", "yaxshi", "bo'ladi", "ertalab", "hafta"):
            self.assertNotEqual(to_cyrillic(uzbek), uzbek, uzbek)  # and none of that catches an Uzbek word

    def test_the_persons_own_spelling_comes_back(self):
        own = translit.own_words("Объектни текшириш. Ильяга қўнғироқ қил")
        self.assertEqual(own, {"obyektni": "объектни", "ilyaga": "ильяга"})  # only what the rules would change
        self.assertEqual(to_cyrillic("Obyektni tekshiraman, Ilyaga qo'ng'iroq qilaman", own=own), "Объектни текшираман, Ильяга қўнғироқ қиламан")
        self.assertEqual(translit.own_words("Эртага соат 10 да ҳисобот юбориш"), {})

    def test_names_to_keep_for_a_message(self):
        keep = translit.latin_words("Call Aziz, Excel, Miso")
        self.assertEqual(translit.names_for("Excel'ни оч", keep), keep)
        self.assertEqual(translit.names_for("Азизга ёз", keep), {"call", "excel", "miso"})  # written in Cyrillic by the person
        self.assertEqual(translit.names_for("Азиз билан Мисо", keep), {"call", "excel"})
        self.assertEqual(translit.names_for("Telegram'да ёз", keep), keep | {"telegram"})  # typed in Latin letters: stays so
        self.assertEqual(translit.names_for("Азизовга ёз", keep), keep)  # another name that only begins the same

    def test_a_respeller_can_be_used_again_and_again(self):
        respell = translit.Respeller(translit.latin_words("Excel"), {"ilyaga": "Ильяга"})
        self.assertEqual(respell("Excel'ni och"), "Excel'ни оч")
        self.assertEqual(respell("ilyaga yoz"), "Ильяга ёз")
        self.assertEqual(respell(""), "")


if __name__ == "__main__":
    unittest.main()
