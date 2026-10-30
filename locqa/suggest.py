"""Варианты исправлений для всех находок.

Каждый вариант от LLM проверяется кодом до ревью: плейсхолдеры как в ru,
у кнопок длина не больше ru × 1.3, после {name} нет аффикса. Не прошёл —
suggestion = None, носитель при желании впишет свой вариант.
"""
from __future__ import annotations

import re
from collections import Counter

from . import glossary as gl
from .lang.kk import SUFFIXES
from .llm import LLM, get_llm, row_context
from .models import Context, Finding

PLACEHOLDER = re.compile(r"\{(\w+)\}")
UI_TOKENS = {"button", "btn", "tab", "title", "label", "header", "action"}
MAX_UI_RATIO = 1.3

_SUFFIX_AFTER_PH = re.compile(
    r"\}-?(?:" + "|".join(sorted({re.escape(s) for s in SUFFIXES}, key=len, reverse=True)) + r")(?![а-яәғқңөұүһі])",
    re.IGNORECASE,
)


def placeholders(text: str) -> Counter:
    return Counter(PLACEHOLDER.findall(text or ""))


def key_tokens(key: str) -> set[str]:
    parts = re.split(r"[_\-.]+", key)
    return {t.lower() for p in parts for t in re.findall(r"[A-Za-z][a-z]*|\d+", p)}


def is_ui_key(key: str, ru: str = "") -> bool:
    """Кнопка/вкладка/заголовок по имени ключа или короткий текст (≤ 3 слов)."""
    return bool(key_tokens(key) & UI_TOKENS) or (bool(ru) and len(ru.split()) <= 3)


def suffix_after_placeholder(text: str) -> bool:
    return bool(_SUFFIX_AFTER_PH.search(text or ""))


def _is_caps(text: str) -> bool:
    letters = [c for c in PLACEHOLDER.sub("", text or "") if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def match_case(ru: str, kk_old: str, cand: str) -> str:
    """КАПС в ru (шаблон интерфейса) — сохраняем его в варианте."""
    if cand and _is_caps(ru) and not _is_caps(cand):
        return _upper_keep_placeholders(cand)
    return cand


def _upper_keep_placeholders(text: str) -> str:
    parts = re.split(r"\{\w+\}", text)  # имена плейсхолдеров не трогаем
    names = PLACEHOLDER.findall(text)
    out = parts[0].upper()
    for name, rest in zip(names, parts[1:]):
        out += "{" + name + "}" + rest.upper()
    return out


NEEDS_KAZAKH = {"untranslated", "same_as_source", "wrong_language"}


def validate(ru: str, kk_old: str, cand: str | None, issue_type: str, key: str) -> str | None:
    """None, если вариант годится, иначе причина отказа."""
    if not cand or not cand.strip():
        return "пустой вариант"
    if cand.strip() == (kk_old or "").strip():
        return "совпадает с текущим kk"
    if issue_type in NEEDS_KAZAKH and cand.strip().lower() == (ru or "").strip().lower():
        return "вариант совпадает с ru — это не перевод"
    if placeholders(cand) != placeholders(ru):
        return "плейсхолдеры не совпадают с ru"
    if suffix_after_placeholder(cand):
        return "аффикс сразу после плейсхолдера"
    short_ui = issue_type == "length_overflow" or (bool(key_tokens(key) & UI_TOKENS) and len(ru.split()) <= 3)
    if short_ui and len(cand) > max(len(ru) * MAX_UI_RATIO, len(ru) + 3):
        return "длиннее ru × 1.3 для элемента интерфейса"
    return None


def restore_placeholders(ru: str, kk: str) -> str | None:
    """Исправление placeholder_mismatch кодом: переименовываем лишние имена в недостающие 1:1."""
    p_ru, p_kk = placeholders(ru), placeholders(kk)
    missing = list((p_ru - p_kk).elements())
    extra = list((p_kk - p_ru).elements())
    if not missing or len(missing) != len(extra):
        return None
    out = kk
    for old, new in zip(extra, missing):
        out = out.replace("{" + old + "}", "{" + new + "}", 1)
    return out if placeholders(out) == p_ru else None


def glossary_hits(ctx: Context, ru: str, limit: int = 12) -> list[str]:
    """Строки глоссария, чей термин встречается в ru (для промпта)."""
    hits = []
    for g in ctx.glossary:
        if not gl.ru_has_term(ru or "", g.get("ru", "")):
            continue
        line = f'{g.get("ru")} → {g.get("kk")}'
        if g.get("allowed_variants"):
            line += f' (допустимо: {", ".join(g["allowed_variants"])})'
        if g.get("comment"):
            line += f' — {g["comment"]}'
        hits.append(line)
        if len(hits) >= limit:
            break
    return hits


BASE_RULES = """You are a senior Kazakh localizer for the mobile game "Grand Mobile" (open-world RP game).
Source language is Russian (ru); English (en) is a reference that shows the UI role of a string.
Write natural, modern Kazakh in Cyrillic, the way Kazakh players talk, consistent with the rest of the file
(see "neighbors" — the existing kk translations nearby show the house style).

Hard rules for every proposed text:
1. Keep placeholders exactly as in ru: same {names}, same count, never translate or rename them.
2. Use the game terms from "glossary" exactly (case endings may change). Brands stay as is (Grand Mobile, Grand Coins...).
3. Never attach a Kazakh affix directly to a placeholder ("{name}-ға", "{count}-ден"): rephrase so the
   placeholder stands alone, e.g. "Алушы: {name}", "{count} дана".
4. For buttons, tabs, titles and other short UI elements the text must not be longer than ru × 1.3.
5. Keep line breaks (\\n), punctuation style and capitalization style of ru (e.g. ALL CAPS stays ALL CAPS).
6. Change only what is needed to fix the reported problem; keep correct parts of the current kk.
Return one result per input item with the same id. If you cannot produce a clearly better text, return an empty string."""

TYPE_TASKS = {
    "untranslated": "The kk text is missing or empty. Translate ru into Kazakh.",
    "same_as_source": "The kk text is just a copy of ru (Russian). Translate it into Kazakh. "
    "If the ru text is a brand, name or a loanword that Kazakh uses unchanged, return an empty string.",
    "wrong_language": "The kk text is in another language (Uzbek, Russian, English...). Translate ru into Kazakh.",
    "placeholder_mismatch": "The kk text has wrong placeholders. Fix them to match ru; keep the rest of kk.",
    "plural_mismatch": "The ICU plural in kk is broken. Return a valid ICU plural with at least the 'other' form.",
    "suffix_harmony": "An affix is glued to a placeholder or breaks vowel harmony. Rephrase minimally.",
    "orthography": "kk has a spelling error (often a Russian letter instead of a Kazakh one). Fix the spelling only.",
    "glossary_violation": "kk does not use the glossary term. Use the glossary translation, keep the rest.",
    "inconsistent_term": "kk uses a rare variant of a term. Use the dominant variant from the evidence.",
    "length_overflow": "kk is too long for a short UI element. Give a shorter Kazakh variant, ≤ ru × 1.3 chars.",
    "machine_translation_suspect": "kk reads like a literal machine translation (calque, Russian word order). "
    "Rewrite it as natural Kazakh.",
}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestion": {"type": "string"},
        "note": {"type": "string"},  # коротко по-русски: что исправлено
    },
    "required": ["suggestion", "note"],
}


def suggest(ctx: Context, findings: list[Finding], llm: LLM | None = None) -> dict:
    """Заполняет finding.suggestion на месте. Возвращает статистику для методологии."""
    llm = llm or get_llm()
    index = {k: i for i, k in enumerate(ctx.order)}
    stats = {"code": 0, "llm_accepted": 0, "rejected": Counter(), "no_suggestion": 0}
    todo: dict[str, list[Finding]] = {}

    for f in findings:
        ru = ctx.ru.get(f.key, f.source)
        kk = ctx.kk.get(f.key, f.target)
        if f.suggestion is not None:
            reason = validate(ru, kk, f.suggestion, f.issue_type, f.key)
            if reason is None:
                continue
            stats["rejected"][reason] += 1
            f.suggestion = None
        if f.issue_type == "placeholder_mismatch":
            fixed = restore_placeholders(ru, kk)
            if fixed and validate(ru, kk, fixed, f.issue_type, f.key) is None:
                f.suggestion = fixed
                stats["code"] += 1
                continue
        todo.setdefault(f.issue_type, []).append(f)

    for issue_type, group in todo.items():
        prompt = BASE_RULES + "\n\nProblem type for all items: " + TYPE_TASKS.get(issue_type, issue_type)
        items, by_id = [], {}
        for i, f in enumerate(group):
            row = row_context(ctx, f.key, index)
            row["id"] = str(i)
            row["problem"] = f.evidence
            row["glossary"] = glossary_hits(ctx, row["ru"])
            row["ui_element"] = is_ui_key(f.key, row["ru"])
            items.append(row)
            by_id[str(i)] = f
        for res in llm.ask(items, prompt, ITEM_SCHEMA, batch_size=15):
            f = by_id[str(res["id"])]
            cand = (res.get("suggestion") or "").strip()
            if not cand:
                continue
            ru, kk = ctx.ru.get(f.key, f.source), ctx.kk.get(f.key, f.target)
            cand = match_case(ru, kk, cand)
            reason = validate(ru, kk, cand, f.issue_type, f.key)
            if reason:
                stats["rejected"][reason] += 1
            else:
                f.suggestion = cand
                stats["llm_accepted"] += 1

    stats["no_suggestion"] = sum(f.suggestion is None for f in findings)
    stats["rejected"] = dict(stats["rejected"])
    return stats
