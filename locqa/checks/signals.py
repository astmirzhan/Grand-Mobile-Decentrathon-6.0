"""Смысловые ошибки, которые видны без LLM: имена и числа.

Работает на любом ARB без ключа API. Тип находок — machine_translation_suspect («другой смысл»),
как у LLM-проверки: смысл kk не совпадает с ru, и это доказано формальным признаком.

- brand_mismatch: латинское имя из ru (и uz — второй свидетель) пропало в kk без транслитерации
  или заменено другим именем («Apple» -> «Google»).
- number_mismatch: числа в ru и kk не совпадают («от 1 до 70» -> «3-тен 90-ға»).

Подмену перевода другим ключом («БАЛАНС» -> «қолма-қол ақша») кодом надёжно не отличить от синонимов
(«Купить» / «Приобрести»): на данных кейса правило давало ~10% точности, поэтому это оставлено LLM.
"""
from __future__ import annotations

import re
from collections import Counter

from ..models import Context, Finding

PLACEHOLDER = re.compile(r"\{\w+\}|%\w")
URL = re.compile(r"https?://\S+")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9&+\-]*[A-Za-z0-9]")
NUMBER = re.compile(r"\d+(?:[ ., ]\d{3})*(?:[.,:]\d+)?")
FRACTION = re.compile(r"\b\d+/\d+\b")
WORD = re.compile(r"[a-zа-яёәғқңөұүһі]+")

# «трёх символов» -> «3 таңба»: число словом в ru и цифрой в kk — не ошибка
RU_NUMBER_WORDS = {
    "1": ("один", "одн", "перв"), "2": ("два", "двух", "две", "втор"), "3": ("три", "трех", "трёх", "трет"),
    "4": ("четыр",), "5": ("пят",), "6": ("шест",), "7": ("сем",), "8": ("восем", "восьм"), "9": ("девят",),
    "10": ("десят",), "100": ("сто",), "1000": ("тысяч",),
}
_TRANSLIT = str.maketrans({
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
})


def _text(s: str) -> str:
    return URL.sub(" ", PLACEHOLDER.sub(" ", s or ""))


def _latin(s: str) -> Counter:
    return Counter(t.lower() for t in LATIN.findall(_text(s)) if len(t) >= 2)


def _names(s: str) -> dict[str, str]:
    """Латинские имена с заглавной буквы (Apple, ID, VK) в исходном написании; «email», «unused» — не имена."""
    return {t.lower(): t for t in LATIN.findall(_text(s)) if len(t) >= 2 and t[0].isupper()}


def _translit_present(token: str, kk: str) -> bool:
    """Ivan -> Иван, Tesla -> Тесла, Taxi -> Такси: сравниваем первые 3 буквы транслитерации."""
    cyr = token.lower().translate(_TRANSLIT)
    low = kk.lower()
    return any(w.startswith(cyr[:3]) for w in WORD.findall(low)) if len(cyr) >= 3 else False


def _numbers(s: str) -> Counter:
    s = FRACTION.sub(" ", _text(s))
    return Counter(re.sub(r"[ ., ](?=\d{3}\b)", "", n) for n in NUMBER.findall(s))


def _finding(ctx: Context, key: str, evidence: str, confidence: float, suggestion: str | None = None) -> Finding:
    return Finding(
        key=key,
        issue_type="machine_translation_suspect",
        severity="high" if confidence >= 0.85 else "medium",
        source=ctx.ru[key],
        target=ctx.kk[key],
        evidence="другой смысл, " + evidence,
        suggestion=suggestion,
        confidence=confidence,
    )


def _pairs(ctx: Context):
    for key in ctx.order:
        ru, kk = ctx.ru.get(key, ""), ctx.kk.get(key, "")
        if ru and kk and kk != ru and key != "currencySymbol":
            yield key, ru, kk


def brand_mismatch(ctx: Context) -> list[Finding]:
    out = []
    for key, ru, kk in _pairs(ctx):
        lost = _latin(ru) - _latin(kk)
        if not lost:
            continue
        uz = _latin(ctx.uz.get(key, ""))
        names = _names(ru)
        # имя считаем брендом, если его сохранил и узбекский перевод (обычные слова он переводит)
        brands = [names[t] for t in lost if t in names and t in uz and not _translit_present(t, kk)]
        if not brands:
            continue
        kk_names = _names(kk)
        added = [kk_names[t] for t in _latin(kk) - _latin(ru) if t in kk_names]
        if added:
            fix = kk.replace(added[0], brands[0]) if len(brands) == len(added) == 1 else None
            out.append(_finding(ctx, key, f"в ru «{brands[0]}», а в kk «{added[0]}»", 0.95, fix))
        else:
            out.append(_finding(ctx, key, f"имя «{', '.join(brands)}» из ru (и uz) пропало в kk", 0.7))
    return out


def number_mismatch(ctx: Context) -> list[Finding]:
    out = []
    for key, ru, kk in _pairs(ctx):
        if URL.search(ru) or URL.search(kk):
            continue  # ссылки локализуют (ru/en в пути, другой id статьи)
        a, b = _numbers(ru), _numbers(kk)
        if a == b:
            continue
        low = ru.lower()
        # kk-цифра, записанная в ru словом, — не ошибка
        extra = Counter({n: c for n, c in (b - a).items() if not any(w in low for w in RU_NUMBER_WORDS.get(n, ()))})
        missing = a - b
        if not extra and not missing:
            continue
        parts = []
        if missing:
            parts.append(f"в kk нет чисел {sorted(missing)} из ru")
        if extra:
            parts.append(f"в kk лишние числа {sorted(extra)}")
        out.append(_finding(ctx, key, "; ".join(parts), 0.85 if missing and extra else 0.7))
    return out


def check(ctx: Context) -> list[Finding]:
    found: dict[str, Finding] = {}
    for f in brand_mismatch(ctx) + number_mismatch(ctx):
        if f.key not in found or f.confidence > found[f.key].confidence:
            found[f.key] = f
    order = {k: i for i, k in enumerate(ctx.order)}
    return sorted(found.values(), key=lambda f: order.get(f.key, 0))
