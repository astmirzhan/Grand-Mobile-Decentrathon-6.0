from __future__ import annotations

import re
from pathlib import Path

from locqa.icu import (
    check_balanced_braces,
    extract_placeholders,
    has_icu_complex,
    validate_plural,
)
from locqa.models import Context, Finding, compute_severity

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]")
_KAZAKH_SPECIFIC_RE = re.compile(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]")
_LATIN_WORD_RE = re.compile(r"[a-zA-Z]+")
_UZBEK_MARKERS_RE = re.compile(r"(?:[ўЎ]|[oOgG]['ʻ’‘`])")
_PLACEHOLDER_STRIP_RE = re.compile(r"\{[^{}]*\}|%[sd]|\<[a-zA-Z0-9_/]+\>")
_LATIN_NUMERO_RE = re.compile(r"(?<=[а-яёА-ЯЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]\s)No(?=\s|$)")

BRAND_WHITELIST: set[str] = {
    "kaspi",
    "kaspi.kz",
    "kaspi gold",
    "kaspi red",
    "kaspi pay",
    "visa",
    "mastercard",
    "apple",
    "google",
    "apple pay",
    "google pay",
    "samsung pay",
    "qr",
    "sms",
    "push",
    "pin",
    "cvv",
    "iban",
    "swift",
    "id",
    "face id",
    "touch id",
    "wi-fi",
    "pdf",
    "vip",
    "ok",
    "grand",
    "pvp",
    "rep",
    "hud",
    "afk",
    "npc",
    "summer rush",
    "carball league",
    "silverstar g63",
}


def _load_external_brands() -> set[str]:
    brands = set(BRAND_WHITELIST)
    for candidate in (Path("brands.txt"), Path("data/brands.txt")):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    brands.add(line)
    return brands


IDENTICAL_KK_RU_LOANWORDS: set[str] = {
    "мин",
    "сек",
    "мин.",
    "макс.",
    "сек.",
    "минут",
    "10 секунд!",
    "%s км",
    "{minutes} мин. {seconds} сек.",
    "{seconds} сек.",
    "бонус",
    "x%s бонус",
    "промокод",
    "профиль",
    "бразилия",
    "беларусь",
    "украина",
    "баскет",
    "шефбургер",
    "баскет 11+11",
    "дилер",
    "инкассатор",
    "онлайн",
    "аккаунт",
    "графика",
    "кабинет",
    "бизнес",
    "вокзал",
    "фракция",
    "логин",
    "аналог",
    "неон",
    "капот",
    "бампер",
    "бак",
    "багаж",
    "авто",
    "стайлинг",
    "нитро",
    "гидравлика",
    "спойлер",
    "турбонаддув",
    "чип-тюнинг",
    "модификация",
    "стандарт",
    "стерео",
    "мастер-лига",
    "кубок",
    "алхимия",
    "аирдроп",
    "лава",
    "энергия",
    "металл",
    "нейрон",
    "картон",
    "маска",
    "пластик",
    "селитра",
    "алмаз",
    "самокат",
    "колба",
    "айсберг",
    "букет",
    "голем",
    "кактус",
    "лента",
    "фейерверк",
    "чемпионат",
    "ранг",
    "банкомат",
    "аксессуар",
    "максимум",
    "минимум",
    "прогресс",
    "нрп",
    "департамент",
    "мегафон",
    "рейтинг",
    "телефон",
    "телефон (планшет)",
    "арена",
    "эвакуатор",
    "класс",
    "бизнес класс",
    "гараж",
    "таймер",
    "финиш!",
    "дерби",
    "картинг",
    "нуга",
    "турмалин",
    "птс",
    "паспорт",
    "котохимик",
    "ивент",
    "экспедиция",
    "автоквест",
    "квест:",
    "локация: арзамас",
    "планшет",
    "бустер",
    "циркуль",
    "торт",
    "клоун",
    "плюс вайб",
    "фейк",
    "минус вайб",
    "команда",
    "лига",
    "лига {name}",
    "кулдаун",
    "контрабанда",
    "маршрут",
    "аукцион",
    "база",
    "мин-чжу",
    "элита",
    "премиум",
    "лимит:",
    "карта",
    "карта:",
    "локация:",
    "сейф",
    "эксклюзив",
    "сервер",
    "grand рулетка",
    "контейнер",
    "тюнинг",
    "рэй",
    "вега",
    "терминал",
    "лидерборд",
    "бинго",
    "тир",
    "финал",
    "гол!",
    "раунд",
    "сканер",
    "сканер\nx{count}",
    "доктор хаос",
    "банк:",
    "рулетка",
    "мини",
    "гранд",
    "фестиваль",
    "лотерея",
    "математика",
    "информатика",
    "физика",
    "география",
    "биология",
    "директор",
    "влад",
}


def _is_exempt_same_as_source(key: str, ru_val: str, ctx: Context, brands: set[str]) -> bool:
    stripped = ru_val.strip()
    if len(stripped) <= 2:
        return True
    low = stripped.lower()
    if low in brands or low in IDENTICAL_KK_RU_LOANWORDS:
        return True
    if key in ctx.en and ctx.en[key].strip().lower() == low:
        return True
    without_ph = _PLACEHOLDER_STRIP_RE.sub("", stripped)
    if not _CYRILLIC_RE.search(without_ph):
        return True
    return False


def _detect_wrong_language(
    key: str,
    ru_val: str,
    kk_val: str,
    ctx: Context,
    ru_placeholders: set[str],
    brands: set[str],
) -> str | None:
    if "english" in key.lower() or kk_val.strip().lower() in brands:
        return None

    uz_val = ctx.uz.get(key, "").strip()
    en_val = ctx.en.get(key, "").strip()

    if en_val and kk_val.strip() == en_val and key not in ("inventoryEquipped",):
        if kk_val.strip().isupper() or any(ch.isdigit() for ch in kk_val):
            return None

    if uz_val and kk_val.strip() == uz_val and uz_val != ru_val.strip():
        if not kk_val.strip().startswith("http"):
            return f"Перевод в kk совпадает с узбекским (kk == uz: '{kk_val}')"

    uz_match = _UZBEK_MARKERS_RE.search(kk_val)
    if uz_match:
        return f"Обнаружены характерные узбекские символы ('{uz_match.group(0)}') в строке '{kk_val}'"

    ru_no_ph = _PLACEHOLDER_STRIP_RE.sub("", ru_val)
    kk_no_ph = _PLACEHOLDER_STRIP_RE.sub("", kk_val)
    for ph in ru_placeholders:
        kk_no_ph = re.sub(rf"\b{re.escape(ph)}\b", "", kk_no_ph)

    if _CYRILLIC_RE.search(ru_no_ph) and not _KAZAKH_SPECIFIC_RE.search(kk_no_ph):
        cyr_chars = len(_CYRILLIC_RE.findall(kk_no_ph))
        lat_chars = sum(len(w) for w in _LATIN_WORD_RE.findall(kk_no_ph))
        if lat_chars > 0 and cyr_chars == 0:
            if en_val and kk_val.strip().lower() == en_val.lower() and en_val.lower() == ru_val.strip().lower():
                return None
            return f"Строка на латинице вместо казахской кириллицы: '{kk_val}'"

    return None


def _suggest_placeholder_fix(ru_val: str, kk_val: str, ru_ph: set[str], kk_ph: set[str]) -> str:
    fixed = kk_val
    missing = ru_ph - kk_ph
    extra = kk_ph - ru_ph

    if len(missing) == 1 and len(extra) == 1:
        m_name = next(iter(missing))
        e_name = next(iter(extra))
        return fixed.replace("{" + e_name + "}", "{" + m_name + "}")

    for m_name in missing:
        pattern = re.compile(rf"(?<!\{{)\b{re.escape(m_name)}\b(?!\}})")
        if pattern.search(fixed):
            fixed = pattern.sub("{" + m_name + "}", fixed)

    return fixed if fixed != kk_val else ""


def check(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    keys = ctx.order if ctx.order else list(ctx.ru.keys())
    brands = _load_external_brands()

    for key in keys:
        if key not in ctx.ru or key.endswith("@description"):
            continue
        ru_val = ctx.ru[key]
        kk_val = ctx.kk.get(key, "")
        section = ctx.sections.get(key, "")
        desc = ctx.descriptions.get(key, "")

        # 1. untranslated
        if key not in ctx.kk or not kk_val.strip():
            reason = "Ключ отсутствует в файле kk" if key not in ctx.kk else "Пустая строка перевода в kk"
            findings.append(
                Finding(
                    key=key,
                    issue_type="untranslated",
                    severity=compute_severity("untranslated", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence=reason,
                )
            )
            continue

        ru_ph = extract_placeholders(ru_val)
        kk_ph = extract_placeholders(kk_val)

        # 2. wrong_language
        wl_evidence = _detect_wrong_language(key, ru_val, kk_val, ctx, ru_ph, brands)
        if wl_evidence:
            findings.append(
                Finding(
                    key=key,
                    issue_type="wrong_language",
                    severity=compute_severity("wrong_language", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence=wl_evidence,
                )
            )

        # 3. same_as_source
        if kk_val.strip() == ru_val.strip() and not _is_exempt_same_as_source(key, ru_val, ctx, brands):
            findings.append(
                Finding(
                    key=key,
                    issue_type="same_as_source",
                    severity=compute_severity("same_as_source", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence=f"Текст в kk не переведён и совпадает с ru ('{ru_val}')",
                )
            )

        # 4. placeholder_mismatch
        if ru_ph != kk_ph:
            ru_fmt = "{" + ", ".join(sorted(ru_ph)) + "}" if ru_ph else "нет"
            kk_fmt = "{" + ", ".join(sorted(kk_ph)) + "}" if kk_ph else "нет"
            suggestion = _suggest_placeholder_fix(ru_val, kk_val, ru_ph, kk_ph)
            findings.append(
                Finding(
                    key=key,
                    issue_type="placeholder_mismatch",
                    severity=compute_severity("placeholder_mismatch", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence=f"в ru плейсхолдеры {ru_fmt}, в kk {kk_fmt}",
                    suggestion=suggestion,
                )
            )

        # 5. plural_mismatch
        plural_errors: list[str] = []
        if not check_balanced_braces(kk_val):
            plural_errors.append("Несбалансированные скобки в kk")
        elif has_icu_complex(ru_val) or has_icu_complex(kk_val):
            if has_icu_complex(ru_val) and not has_icu_complex(kk_val):
                plural_errors.append("В ru используется ICU plural/select, а в kk — обычная строка")
            else:
                plural_errors.extend(validate_plural(kk_val, lang="kk"))

        if plural_errors:
            findings.append(
                Finding(
                    key=key,
                    issue_type="plural_mismatch",
                    severity=compute_severity("plural_mismatch", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence="; ".join(plural_errors),
                )
            )

        # 6. Латинское 'No' вместо знака номера '№'
        if "№" in ru_val and _LATIN_NUMERO_RE.search(kk_val):
            findings.append(
                Finding(
                    key=key,
                    issue_type="orthography",
                    severity=compute_severity("orthography", key, section, desc),
                    source=ru_val,
                    target=kk_val,
                    evidence="Латинское 'No' вместо символа номера '№'",
                    suggestion=_LATIN_NUMERO_RE.sub("№", kk_val),
                )
            )

    return findings