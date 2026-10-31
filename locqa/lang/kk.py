"""Kazakh language profile: letters, affixes, plural categories, stemming."""
import re

# Russian look-alike letter -> Kazakh letter(s) that a typist may have replaced.
LETTER_PAIRS = {
    "а": "ә",
    "г": "ғ",
    "к": "қ",
    "н": "ң",
    "о": "ө",
    "у": "ұү",
    "х": "һ",
    "и": "і",
}

# Kazakh-specific letters (lowercase).
KK_LETTERS = set("әғқңөұүһі")

# Case and number affixes with all vowel-harmony / consonant-assimilation variants.
# Used to detect a hard-coded affix right after a runtime placeholder: {name}-ға.
SUFFIXES = [
    # dative
    "ға", "ге", "қа", "ке", "на", "не",
    # locative
    "да", "де", "та", "те", "нда", "нде",
    # ablative
    "дан", "ден", "тан", "тен", "нан", "нен",
    # genitive
    "ның", "нің", "дың", "дің", "тың", "тің",
    # accusative
    "ны", "ні", "ды", "ді", "ты", "ті",
    # instrumental
    "мен", "бен", "пен",
    # plural
    "лар", "лер", "дар", "дер", "тар", "тер",
    # possessive 3rd person
    "сы", "сі",
]

# Wider set of inflectional endings used to accept "stem + endings" as one word.
INFLECTIONS = sorted(set(SUFFIXES + [
    "ы", "і", "а", "е", "н", "ым", "ім", "ың", "ің", "ыңыз", "іңіз", "сыз", "сіз",
    "ымыз", "іміз", "лық", "лік", "дық", "дік", "тық", "тік", "ша", "ше",
    "ғы", "гі", "қы", "кі", "шы", "ші",
]), key=len, reverse=True)

PLURAL_CATEGORIES = ["one", "other"]

# Latin homoglyphs that sneak into Cyrillic words -> Cyrillic replacement.
LATIN_TO_CYRILLIC = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "i": "і", "k": "к", "h": "һ", "b": "ь",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "I": "І", "K": "К",
    "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

# Final voiceless consonants alternate before a vowel affix: көлік -> көлігі, сыйлық -> сыйлығы.
_ALTERNATING_FINALS = "кқп"

WORD_RE = re.compile(r"[^\W\d_]+")
CYRILLIC_RE = re.compile(r"[а-яёәғқңөұүһі]", re.IGNORECASE)
LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def words(text: str) -> list[str]:
    """Lowercased letter-only tokens."""
    return [w.lower() for w in WORD_RE.findall(text or "")]


def stem(word: str) -> str:
    """Conservative Kazakh stem: lowercase, drop an alternating final к/қ/п
    and the soft sign of Russian loans (инвентарь -> инвентарыңыз)."""
    w = word.lower()
    if len(w) > 3 and w.endswith("ь"):
        w = w[:-1]
    if len(w) > 3 and w[-1] in _ALTERNATING_FINALS:
        w = w[:-1]
    return w


def is_inflection_chain(rest: str, depth: int = 3) -> bool:
    """True if `rest` is empty or a chain of up to `depth` known endings."""
    if not rest:
        return True
    if depth == 0:
        return False
    return any(rest.startswith(s) and is_inflection_chain(rest[len(s):], depth - 1)
               for s in INFLECTIONS)


def word_has_stem(word: str, base: str) -> bool:
    """Does an inflected Kazakh `word` derive from `base` (e.g. отбасының <- отбасы)?

    Long stems match by prefix; short stems (үй) require the rest to be known endings,
    so that үй does not match үйрену.
    """
    w, s = word.lower(), stem(base)
    if not w.startswith(s):
        return False
    if len(s) >= 4:
        return True
    return is_inflection_chain(w[len(s):])


_BACK_VOWELS = set("аоұыуяё")
_FRONT_VOWELS = set("әөүіеи")
_VOWELS = _BACK_VOWELS | _FRONT_VOWELS
_SONORANTS = set("рйу")
_NASALS = set("мнң")
_VOICED = set("злж")

# affix family -> (back, front) forms keyed by class of the preceding sound
_AFFIXES = {
    "plural":   {"vowel": ("лар", "лер"), "sonorant": ("лар", "лер"), "nasal": ("дар", "дер"),
                 "voiced": ("дар", "дер"), "voiceless": ("тар", "тер")},
    "genitive": {"vowel": ("ның", "нің"), "sonorant": ("дың", "дің"), "nasal": ("ның", "нің"),
                 "voiced": ("дың", "дің"), "voiceless": ("тың", "тің")},
    "accusative": {"vowel": ("ны", "ні"), "sonorant": ("ды", "ді"), "nasal": ("ды", "ді"),
                   "voiced": ("ды", "ді"), "voiceless": ("ты", "ті")},
    "dative":   {"vowel": ("ға", "ге"), "sonorant": ("ға", "ге"), "nasal": ("ға", "ге"),
                 "voiced": ("ға", "ге"), "voiceless": ("қа", "ке")},
    "locative": {"vowel": ("да", "де"), "sonorant": ("да", "де"), "nasal": ("да", "де"),
                 "voiced": ("да", "де"), "voiceless": ("та", "те")},
    "ablative": {"vowel": ("дан", "ден"), "sonorant": ("дан", "ден"), "nasal": ("нан", "нен"),
                 "voiced": ("дан", "ден"), "voiceless": ("тан", "тен")},
    "instrumental": {"vowel": ("мен", "мен"), "sonorant": ("мен", "мен"), "nasal": ("мен", "мен"),
                     "voiced": ("бен", "бен"), "voiceless": ("пен", "пен"), "l": ("мен", "мен")},
    "possessive3": {"vowel": ("сы", "сі"), "sonorant": ("ы", "і"), "nasal": ("ы", "і"),
                    "voiced": ("ы", "і"), "voiceless": ("ы", "і")},
}
AFFIX_FAMILY = {form: fam for fam, table in _AFFIXES.items()
                for pair in table.values() for form in pair}
# "на/не" and "нда/нде" are dative/locative after possessive; "сы/сі" possessive.
AFFIX_FAMILY.update({"на": "dative", "не": "dative", "нда": "locative", "нде": "locative"})


def _sound_class(ch: str, family: str = "") -> str:
    if ch == "л" and family == "instrumental":
        return "l"
    if ch in _VOWELS:
        return "vowel"
    if ch in _SONORANTS:
        return "sonorant"
    if ch in _NASALS:
        return "nasal"
    if ch in _VOICED:
        return "voiced"
    return "voiceless"


def is_front(word: str) -> bool:
    """Vowel harmony of a word, decided by its last vowel."""
    for ch in reversed(word.lower()):
        if ch in _FRONT_VOWELS:
            return True
        if ch in _BACK_VOWELS:
            return False
    return False


def harmonize(base: str, family: str) -> str:
    """Correct form of an affix family for `base`: harmonize('үй', 'dative') -> 'ге'."""
    w = base.lower()
    last = w[-1] if w else "а"
    back, front = _AFFIXES[family][_sound_class(last, family)]
    return front if is_front(w) else back


# Possessive -ы/-і/-сы/-сі are part of the root for our purposes (отбасы, көлігі).
_SPLITTABLE = sorted((a for a, fam in AFFIX_FAMILY.items() if fam != "possessive3"),
                     key=len, reverse=True)


def split_affixes(word: str) -> tuple[str, list[str]]:
    """Split the longest chain (≤3) of case/number affixes off the end of `word`.

    ойнаушыларды -> ('ойнаушы', ['лар', 'ды']). Root keeps at least 3 letters.
    """
    w = word.lower()

    def chain(rest, depth):
        if not rest:
            return []
        if depth == 0:
            return None
        for s in _SPLITTABLE:
            if rest.startswith(s):
                tail = chain(rest[len(s):], depth - 1)
                if tail is not None:
                    return [s, *tail]
        return None

    for i in range(3, len(w) + 1):
        parts = chain(w[i:], 3)
        if parts is not None:
            return w[:i], parts
    return w, []


def inflect(base: str, affixes: list[str]) -> str:
    """Attach affixes to `base` re-harmonizing each one: inflect('скин', ['лар']) -> 'скиндер'."""
    out = base
    for a in affixes:
        fam = AFFIX_FAMILY.get(a)
        out += harmonize(out, fam) if fam else a
    return out


def is_mixed_script(word: str) -> bool:
    return bool(CYRILLIC_RE.search(word)) and bool(LATIN_RE.search(word))
