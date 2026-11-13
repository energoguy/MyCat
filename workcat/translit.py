"""Uzbek between its two alphabets, Cyrillic and Latin.

People write Uzbek in either alphabet and expect the answer in the one they used. The
small offline model writes Uzbek better in Latin letters, and now and then answers in
the other alphabet than the one asked for. So the alphabet is not left to the model: a
message in Cyrillic is handed to it in Latin letters, and its answer is put back into
Cyrillic here, letter for letter, by the rules of the two official alphabets.

    to_latin("Эртага қўнғироқ қил")       ->  "Ertaga qo'ng'iroq qil"
    to_cyrillic("Ertaga qo'ng'iroq qil")  ->  "Эртага қўнғироқ қил"

Cyrillic to Latin is exact. The way back cannot know everything (a soft sign, or which
"s" used to be a "ц"), so the commonest borrowed words are listed below, names of
programs and music are left as they are, and words the person wrote themselves come back
exactly as they wrote them.
"""
from __future__ import annotations

import re

_VOWELS = frozenset("аеёиоуэюяўы")
_VOWELS_BEFORE_E = frozenset("аоуўэюяё")  # after these a bare Latin "e" is э: аэро, поэзия, дуэт
_SOFT_OR_HARD = frozenset("ъь")
_IOTATED = frozenset("еёюя")

_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ч": "ch", "ш": "sh", "щ": "sh",
    "ы": "i", "э": "e", "ю": "yu", "я": "ya", "ё": "yo", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
_TO_CYRILLIC = {
    "a": "а", "b": "б", "d": "д", "f": "ф", "g": "г", "h": "ҳ", "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х", "z": "з",
}

# Borrowed words whose Cyrillic spelling the rules cannot work out from the Latin one.
_BORROWED = {
    "kompyuter": "компьютер", "film": "фильм", "albom": "альбом", "rol": "роль", "parol": "пароль", "nol": "ноль",
    "medal": "медаль", "kalendar": "календарь", "intervyu": "интервью", "sirk": "цирк", "sement": "цемент",
    "konsert": "концерт", "kontsert": "концерт", "protsent": "процент", "protsess": "процесс", "retsept": "рецепт",
    "dotsent": "доцент", "litsey": "лицей", "litsenziya": "лицензия", "stansiya": "станция", "konferensiya": "конференция",
    "yanvar": "январь", "fevral": "февраль", "aprel": "апрель", "iyun": "июнь", "iyul": "июль", "sentabr": "сентябрь",
    "sentyabr": "сентябрь", "oktabr": "октябрь", "oktyabr": "октябрь", "noyabr": "ноябрь", "dekabr": "декабрь",
}

_SIGNS = re.compile("[ʻʼ’‘`]")  # what people type for the sign in o' and g'
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:'{1,2}[A-Za-z]+)*(?:(?<=[ogOG])')?")
_CYRILLIC_WORD = re.compile(r"[Ѐ-ӿ]+")
_ENDING = re.compile(r"'?(?:ni|ning|ga|ka|qa|da|dan|dagi|lar|li|siz|mi|chi)[a-z']*|'[a-z']+")  # Excel'ni, Chromeda
# Letters and pairs that Uzbek in Latin letters does not have: such a word is English
# (the, with, check, book, copy) and is left as it is rather than respelled into nonsense.
_NOT_UZBEK = re.compile(r"w|c(?!h)|th|ph|ck|ee|oo|ou|gh|tion|[bcdfghjklmnpqrstvxz]y$")


def _cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def to_latin(text: str) -> str:
    """Uzbek in Cyrillic letters, in Latin letters. Everything else is left as it is."""
    out: list = []
    n = len(text)
    for i, ch in enumerate(text):
        if not _cyrillic(ch):
            out.append(ch)
            continue
        low = ch.lower()
        before = text[i - 1].lower() if i else ""
        after = text[i + 1].lower() if i + 1 < n else ""
        if low == "е":  # "ye" where a word or a syllable starts with it: ер, поезд, объект
            latin = "ye" if not _cyrillic(before) or before in _VOWELS or before in _SOFT_OR_HARD else "e"
        elif low == "ц":
            latin = "ts" if before in _VOWELS else "s"
        elif low == "ъ":
            latin = "" if after in _IOTATED else "'"
        elif low == "ь":
            latin = ""
        elif low == "с" and after == "ҳ":
            latin = "s'"  # Исҳоқ is Is'hoq: without the sign it would read as "sh"
        else:
            latin = _TO_LATIN.get(low)
            if latin is None:  # a Cyrillic letter Uzbek does not use
                out.append(ch)
                continue
        if ch != low and latin:
            shouting = (i + 1 < n and text[i + 1].isupper()) or (i > 0 and text[i - 1].isupper() and not (i + 1 < n and text[i + 1].islower()))
            latin = latin.upper() if shouting else latin[0].upper() + latin[1:]
        out.append(latin)
    return "".join(out)


def _letters(word: str) -> str:
    """One Latin word, letter for letter, in Cyrillic."""
    low = word.lower()
    out: list = []
    i, n = 0, len(low)
    while i < n:
        ch = low[i]
        after = low[i + 1] if i + 1 < n else ""
        opens = i == 0 or (bool(out) and out[-1][-1].lower() in _VOWELS)  # a word or a syllable starts here
        step = 1
        if ch in "og" and after == "'":
            made, step = ("ў" if ch == "o" else "ғ"), 2
        elif ch == "s" and after == "h":
            made, step = "ш", 2
        elif ch == "c" and after == "h":
            made, step = "ч", 2
        elif ch == "s" and low.startswith("'h", i + 1):
            made, step = "с", 2  # Is'hoq: the sign only keeps the s and the h apart
        elif ch == "y":
            if low.startswith("o'", i + 1):
                made = "й"  # yo'q is йўқ, not ёқ
            elif after == "a":
                made, step = "я", 2
            elif after == "o":
                made, step = "ё", 2
            elif after == "u":
                made, step = "ю", 2
            elif after == "e":
                made, step = ("е" if opens else "ье"), 2
            else:
                made = "й"
        elif ch == "e":  # эртага, поэзия; but клиент
            made = "э" if i == 0 or (bool(out) and out[-1][-1].lower() in _VOWELS_BEFORE_E) else "е"
        elif ch == "t" and (low.startswith("siya", i + 1) or low.startswith("sion", i + 1)):
            made, step = "ц", 2  # informatsiya
        elif ch == "s" and i and low[i - 1] in "kp" and low.startswith("iya", i + 1):
            made = "ц"  # funksiya, aksiya
        elif ch == "'":
            made = "ъ"  # ma'no
        else:
            made = _TO_CYRILLIC.get(ch, ch)
        if word[i].isupper():
            made = made[0].upper() + made[1:]
        out.append(made)
        i += step
    made = "".join(out)
    return made.upper() if len(word) > 1 and word.isupper() else made


def _cased(made: str, like: str) -> str:
    """`made` with the capital letters of `like`. Capitals `made` already has are kept."""
    if len(like) > 1 and like.isupper():
        return made.upper()
    if like[:1].isupper():
        return made[:1].upper() + made[1:]
    return made


class Respeller:
    """Puts Uzbek written in Latin letters into Cyrillic letters, again and again with
    the same names to leave alone (an answer is respelled many times while it arrives).

    keep  Latin words to leave as they are: names of programs, sites and music. A name
          may carry an Uzbek ending: Excel'ni becomes Excel'ни.
    own   {latin word: the person's own Cyrillic spelling}, from own_words()."""

    def __init__(self, keep=(), own=None):
        self.kept = frozenset(name.lower() for name in keep)
        self.known = {**_BORROWED, **(own or {})}
        self.names: dict = {}  # by their first three letters, longest first
        for name in sorted((name for name in self.kept if len(name) >= 3), key=len, reverse=True):
            self.names.setdefault(name[:3], []).append(name)
        self.stems = sorted((word for word in self.known if len(word) >= 4), key=len, reverse=True)

    def __call__(self, text: str) -> str:
        return _LATIN_WORD.sub(self._word, _SIGNS.sub("'", text))

    def _word(self, match) -> str:
        word = match.group(0)
        low = word.lower()
        if low in self.kept:
            return word
        if low in self.known:
            return _cased(self.known[low], word)
        for name in self.names.get(low[:3], ()):
            if low.startswith(name) and _ENDING.fullmatch(low[len(name):]):
                ending = word[len(name):]
                sign = "'" if ending.startswith("'") else ""
                return word[: len(name)] + sign + _letters(ending[len(sign):])
        for stem in self.stems:
            if low.startswith(stem) and _ENDING.fullmatch(low[len(stem):]):
                known = self.known[stem].rstrip("ь")  # компьютер + да; сентябрь + да = сентябрда
                return _cased(known, word[: len(stem)]) + _letters(word[len(stem):].lstrip("'"))
        if _NOT_UZBEK.search(low):
            return word
        return _letters(word)


def to_cyrillic(text: str, keep=(), own=None) -> str:
    """Uzbek in Latin letters, in Cyrillic letters. See Respeller for `keep` and `own`."""
    return Respeller(keep, own)(text)


def own_words(text: str) -> dict:
    """The words of a Cyrillic text that would not come back the same from Latin letters
    (компьютер, сентябрь, a name), by their Latin spelling, so that an answer can use
    them exactly as the person wrote them."""
    found: dict = {}
    for match in _CYRILLIC_WORD.finditer(text):
        word = match.group(0)
        latin = to_latin(word)
        if not latin or to_cyrillic(latin) == word:
            continue
        before = text[: match.start()].rstrip()
        if not before or before[-1] in ".!?\n":  # the capital is the sentence's, not the word's
            word = word[0].lower() + word[1:] if not word.isupper() else word
        found.setdefault(latin.lower(), word)
    return found


def latin_words(text: str) -> set:
    """The Latin words of a text, in lower case: what to_cyrillic() should keep."""
    return {word.lower() for word in _LATIN_WORD.findall(_SIGNS.sub("'", text))}


def names_for(text: str, keep) -> set:
    """The names to keep in Latin letters when answering `text`, a message in Cyrillic.

    Whatever the person typed in Latin letters themselves is added ("Excel'ни оч"). And
    a name they have just written in Cyrillic is taken out: with a task "Call Aziz" on
    the list, someone who writes "Азизга" wants to read "Азизга", not "Azizга"."""
    theirs = [to_latin(word).lower() for word in _CYRILLIC_WORD.findall(text)]

    def written(name: str) -> bool:
        return any(word == name or (len(name) >= 3 and word.startswith(name) and _ENDING.fullmatch(word[len(name):])) for word in theirs)

    return {name for name in (name.lower() for name in keep) if not written(name)} | latin_words(text)
