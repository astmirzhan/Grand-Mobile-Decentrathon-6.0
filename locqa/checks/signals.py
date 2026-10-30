"""Code signals for localization QA: brand names and number consistency."""
from __future__ import annotations

import re
from typing import Any

from locqa.models import Finding

_LATIN_BRAND_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_]+\b")
_URL_RE = re.compile(r"https?://\S+")

# Simple Russian-to-Latin transliteration mapping for brand name checking
_LATIN_TO_CYR_TRANSLIT = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з",
}

_RU_NUM_WORDS = {
    "один": 1, "одного": 1, "одна": 1, "одну": 1,
    "два": 2, "двух": 2, "две": 2, "двум": 2,
    "три": 3, "трех": 3, "трёх": 3, "трем": 3, "трём": 3,
    "четыре": 4, "четырех": 4, "четырёх": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
}


def _approx_translit(latin_word: str) -> str:
    res = []
    low = latin_word.lower()
    i = 0
    while i < len(low):
        if low[i:i+2] == "sh":
            res.append("ш")
            i += 2
        elif low[i:i+2] == "ch":
            res.append("ч")
            i += 2
        else:
            res.append(_LATIN_TO_CYR_TRANSLIT.get(low[i], low[i]))
            i += 1
    return "".join(res)


def brand_mismatch(ctx: Any) -> list[Finding]:
    """Detects brand names from source that were dropped or replaced in target."""
    findings: list[Finding] = []
    order = getattr(ctx, "order", list(ctx.ru.keys()))
    uz_dict = getattr(ctx, "uz", {})

    for key in order:
        if key not in ctx.ru or key not in ctx.kk:
            continue
        ru_val = ctx.ru[key]
        kk_val = ctx.kk[key]
        if not kk_val:
            continue

        ru_brands = _LATIN_BRAND_RE.findall(ru_val)
        if not ru_brands:
            continue

        uz_val = uz_dict.get(key, "")

        for brand in ru_brands:
            # If uz is provided, brand must also be preserved in uz (otherwise it's a common word)
            if uz_val and brand not in uz_val:
                continue

            # Check if brand is in kk
            if brand in kk_val:
                continue

            # Check if brand was transliterated into Cyrillic (e.g. Tesla -> Тесла)
            cyr_translit = _approx_translit(brand)
            kk_words_low = re.findall(r"[а-яёәғқңөұүһі]+", kk_val.lower())
            if any(w == cyr_translit or w.startswith(cyr_translit[:3]) for w in kk_words_low if len(cyr_translit) >= 3):
                continue

            # Check if brand was replaced with another Latin brand in kk
            kk_brands = _LATIN_BRAND_RE.findall(kk_val)
            foreign_kk_brands = [b for b in kk_brands if b not in ru_brands]

            if foreign_kk_brands:
                wrong_brand = foreign_kk_brands[0]
                suggestion = kk_val.replace(wrong_brand, brand)
                findings.append(
                    Finding(
                        key=key,
                        issue_type="machine_translation_suspect",
                        severity="low",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Имя/бренд '{brand}' заменён на '{wrong_brand}'",
                        suggestion=suggestion,
                        confidence=0.95,
                    )
                )
            else:
                findings.append(
                    Finding(
                        key=key,
                        issue_type="machine_translation_suspect",
                        severity="low",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Имя/бренд '{brand}' отсутствует в переводе",
                        suggestion=None,
                        confidence=0.7,
                    )
                )

    return findings


def _extract_numbers(text: str) -> set[int | float | str]:
    cleaned = _URL_RE.sub("", text)
    # Handle thousands separators like 50 000 000 or 50.000.000
    cleaned = re.sub(r"(\d+)[\s.](\d{3}(?:[\s.]\d{3})*)", lambda m: m.group(1) + m.group(2).replace(" ", "").replace(".", ""), cleaned)
    
    nums: set[int | float | str] = set()
    # Find fractions like 1/4
    for frac in re.findall(r"\b\d+/\d+\b", cleaned):
        nums.add(frac)
    
    cleaned_no_frac = re.sub(r"\b\d+/\d+\b", "", cleaned)
    for n_str in re.findall(r"\b\d+\b", cleaned_no_frac):
        nums.add(int(n_str))
        
    return nums


def number_mismatch(ctx: Any) -> list[Finding]:
    """Detects mismatches in numeric values between source and target."""
    findings: list[Finding] = []
    order = getattr(ctx, "order", list(ctx.ru.keys()))

    for key in order:
        if key not in ctx.ru or key not in ctx.kk:
            continue
        ru_val = ctx.ru[key]
        kk_val = ctx.kk[key]
        if not kk_val:
            continue

        ru_nums = _extract_numbers(ru_val)
        kk_nums = _extract_numbers(kk_val)

        # Check for fraction 1/4 -> ширек, 1/2 -> жарты
        if "1/4" in ru_nums and "ширек" in kk_val.lower():
            ru_nums.remove("1/4")
        if "1/2" in ru_nums and any(w in kk_val.lower() for w in ("жарты", "жартысы")):
            ru_nums.remove("1/2")

        # Check for Russian words expressing numbers
        ru_words = [w.lower() for w in re.findall(r"[а-яёА-ЯЁ]+", ru_val)]
        for w in ru_words:
            if w in _RU_NUM_WORDS:
                num_val = _RU_NUM_WORDS[w]
                if num_val in kk_nums:
                    ru_nums.add(num_val)

        if ru_nums != kk_nums:
            findings.append(
                Finding(
                    key=key,
                    issue_type="machine_translation_suspect",
                    severity="low",
                    source=ru_val,
                    target=kk_val,
                    evidence=f"Несовпадение чисел: в ru {sorted(str(x) for x in ru_nums)}, в kk {sorted(str(x) for x in kk_nums)}",
                    suggestion=None,
                    confidence=0.85,
                )
            )

    return findings


def check(ctx: Any) -> list[Finding]:
    """Runs all signal checks."""
    return brand_mismatch(ctx) + number_mismatch(ctx)
