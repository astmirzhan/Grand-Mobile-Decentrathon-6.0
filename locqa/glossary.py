"""Glossary loading and term matching by word stem.

glossary.csv columns: ru, kk, en, comment, allowed_variants
allowed_variants holds extra accepted Kazakh forms separated by "|" (player slang, synonyms).
"""
import csv
import re

from locqa.lang import kk as kk_lang

# Russian inflectional endings (nouns + adjectives), longest first.
RU_ENDINGS = sorted({
    "а", "я", "о", "е", "ё", "ы", "и", "у", "ю", "ь",
    "ой", "ей", "ёй", "ом", "ем", "ём", "ам", "ям", "ами", "ями", "ах", "ях", "ов", "ев",
    "ью", "ия", "ии", "ию", "ие", "ий", "ием", "иям", "ями",
    "ый", "ая", "яя", "ое", "ее", "ые", "ого", "его", "ому", "ему", "ым", "им", "ых", "их",
    "ую", "юю",
}, key=len, reverse=True)

_LATIN_WORD = re.compile(r"^[a-z0-9]+$")


def load_glossary(path) -> list[dict]:
    """Read glossary.csv into dicts; allowed_variants becomes a list of strings."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not (row.get("ru") or "").strip() or not (row.get("kk") or "").strip():
                continue
            row = {k: (v or "").strip() for k, v in row.items() if k}
            variants = row.get("allowed_variants", "")
            row["allowed_variants"] = [v.strip() for v in variants.split("|") if v.strip()]
            rows.append(row)
    return rows


def ru_stem(word: str) -> str:
    """Strip one Russian ending, keeping at least 3 letters."""
    w = word.lower()
    if _LATIN_WORD.match(w):
        return w
    for end in RU_ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[: -len(end)]
    return w


def ru_word_matches(word: str, term_word: str) -> bool:
    w, s = word.lower(), ru_stem(term_word)
    if _LATIN_WORD.match(s):
        return w == s
    if not w.startswith(s):
        return False
    rest = w[len(s):]
    return rest == "" or rest in RU_ENDINGS


def _phrase_in(text_words: list[str], phrase: str, match) -> bool:
    """All words of `phrase` occur as a contiguous run in `text_words`."""
    parts = kk_lang.words(phrase)
    if not parts:
        return False
    n = len(parts)
    for i in range(len(text_words) - n + 1):
        if all(match(text_words[i + j], parts[j]) for j in range(n)):
            return True
    return False


def ru_has_term(text: str, term: str) -> bool:
    return _phrase_in(kk_lang.words(text), term, ru_word_matches)


def kk_has_term(text: str, term: str) -> bool:
    return _phrase_in(kk_lang.words(text), term, kk_lang.word_has_stem)


def kk_forms(entry: dict) -> list[str]:
    return [entry["kk"], *entry.get("allowed_variants", [])]


def kk_has_any(text: str, entry: dict) -> bool:
    return any(kk_has_term(text, form) for form in kk_forms(entry))
