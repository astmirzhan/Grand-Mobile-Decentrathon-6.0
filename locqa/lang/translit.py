"""Kazakh Cyrillic -> Latin transliteration (experimental 2021-style mapping).

Placeholders {name}, tags <g>...</g> and escapes stay untouched.
"""
import re

KK_TO_LATIN = {
    "а": "a", "ә": "ä", "б": "b", "в": "v", "г": "g", "ғ": "ğ", "д": "d", "е": "e",
    "ё": "io", "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "q", "л": "l",
    "м": "m", "н": "n", "ң": "ñ", "о": "o", "ө": "ö", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ұ": "ū", "ү": "ü", "ф": "f", "х": "h", "һ": "h", "ц": "ts",
    "ч": "ch", "ш": "ş", "щ": "şş", "ъ": "", "ы": "y", "і": "ı", "ь": "", "э": "e",
    "ю": "iu", "я": "ia",
}
_UPPER_SPECIAL = {"и": "İ", "й": "İ", "і": "I"}

_PROTECTED = re.compile(r"(\{[^{}]*\}|<[^<>]+>|\\[nt]|%[sd])")


def _letter(ch: str) -> str:
    low = ch.lower()
    if low not in KK_TO_LATIN:
        return ch
    if ch == low:
        return KK_TO_LATIN[low]
    if low in _UPPER_SPECIAL:
        return _UPPER_SPECIAL[low]
    latin = KK_TO_LATIN[low]
    return _upper(latin[:1]) + latin[1:]


def _upper(s: str) -> str:
    """Uppercase that keeps the dot: i -> İ (dotless ı -> I)."""
    return s.replace("i", "İ").upper()


def _word(word: str) -> str:
    out = "".join(_letter(ch) for ch in word)
    # Whole-word uppercase stays uppercase: ШЫҒУ -> ŞYĞU, not ŞyĞU.
    return out.upper().replace("İ", "İ") if len(word) > 1 and word.isupper() else out


def _plain(text: str) -> str:
    return re.sub(r"[^\W\d_]+", lambda m: _word(m.group()), text)


def to_latin(text: str) -> str:
    parts = _PROTECTED.split(text)
    return "".join(p if i % 2 else _plain(p) for i, p in enumerate(parts))
