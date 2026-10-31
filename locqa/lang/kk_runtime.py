"""Correct Kazakh case affix for a value inserted at runtime ({name}, {count}, {provider}).

A hard-coded affix after a placeholder ({name}-ға) is wrong for half of the values, because
the affix depends on the last sound of the value. These helpers pick it from the value itself:

    inflect_value("Айдос", "dative")    -> "Айдосқа"
    inflect_value("Әлия", "dative")     -> "Әлияға"
    inflect_value("5", "ablative")      -> "5-тен"     (бес)
    inflect_value("100", "dative")      -> "100-ге"    (жүз)
    inflect_value("Google", "dative")   -> "Google-ға"

The same rules are ported to Dart in integrations/flutter/kk_affix, so the game can inflect the
value before passing it to the localized string. Parity is checked on shared test vectors.
"""
import re

from locqa.lang.kk import harmonize

CASES = ("dative", "locative", "ablative", "genitive", "accusative", "instrumental", "plural")

_UNITS = ["нөл", "бір", "екі", "үш", "төрт", "бес", "алты", "жеті", "сегіз", "тоғыз"]
_TENS = ["", "он", "жиырма", "отыз", "қырық", "елу", "алпыс", "жетпіс", "сексен", "тоқсан"]

# Latin letters (official Kazakh Latin + English nicknames) -> Cyrillic sound
_LATIN = {
    "a": "а", "ä": "ә", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "ğ": "ғ",
    "h": "һ", "i": "и", "ı": "ы", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "ñ": "ң",
    "o": "о", "ö": "ө", "p": "п", "q": "қ", "r": "р", "s": "с", "ş": "ш", "t": "т", "u": "у",
    "ū": "ұ", "ü": "ү", "v": "в", "w": "у", "x": "х", "y": "и", "z": "з",
}
_LATIN_CONSONANTS = set("bcdfghjklmnpqrstvwxz")
_TRAILING_NUMBER = re.compile(r"(\d+)(?:[.,]\d+)?$")


def number_word(n: int) -> str:
    """The spoken word that ends the number: 5 -> бес, 40 -> қырық, 100 -> жүз, 2000 -> мың."""
    if n == 0:
        return _UNITS[0]
    if n % 10:
        return _UNITS[n % 10]
    if n % 100:
        return _TENS[(n % 100) // 10]
    if n % 1000:
        return "жүз"
    if n % 1_000_000:
        return "мың"
    if n % 1_000_000_000:
        return "миллион"
    return "миллиард"


def spoken_tail(value: str) -> str:
    """Lowercase Cyrillic form of how the value ends when read aloud."""
    v = value.strip().rstrip(".,!?:;)»\"'").strip()
    m = _TRAILING_NUMBER.search(v)
    if m:
        frac = re.search(r"[.,](\d+)$", v)
        return number_word(int(frac.group(1) if frac else m.group(1)))
    word = re.findall(r"[^\W\d_]+", v)
    if not word:
        return "а"
    w = word[-1].lower()
    if all(ch in _LATIN for ch in w):
        # Silent final e in English names: Google, Apple are read гугл, эппл.
        if len(w) > 2 and w.endswith("e") and w[-2] in _LATIN_CONSONANTS:
            w = w[:-1]
        w = "".join(_LATIN[ch] for ch in w)
    return w.rstrip("ьъ") or "а"


def _needs_hyphen(value: str) -> bool:
    """Kazakh spelling: hyphen after digits and Latin-script words (100-ге, Google-ға)."""
    v = value.strip()
    return bool(v) and (v[-1].isdigit() or v[-1].lower() in _LATIN)


def affix(value: str, case: str) -> str:
    if case not in CASES:
        raise ValueError(f"unknown case {case!r}, expected one of {CASES}")
    return harmonize(spoken_tail(value), case)


def inflect_value(value: str, case: str) -> str:
    a = affix(value, case)
    if value.strip().isupper() and not value.strip().isdigit():
        a = a.upper()
    return f"{value}{'-' if _needs_hyphen(value) else ''}{a}"
