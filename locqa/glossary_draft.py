"""Черновик глоссария для Человека 3: LLM выписывает игровые термины, код считает частоты.

    python -m locqa.glossary_draft --source data/intl_ru.arb --target data/intl_kk.arb \
        --ref data/intl_en.arb --out glossary_draft.csv

Колонки: ru, kk, en, comment, allowed_variants (+ служебные category, ru_rows, kk_coverage).
kk_coverage — доля строк с ru-термином, где в kk есть основа kk-термина: низкое значение
значит либо термин переводят по-разному (кандидат в inconsistent_term), либо LLM ошибся.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict

from ._load import build_context
from .llm import LLM

CHUNK = 150
COLUMNS = ["ru", "kk", "en", "comment", "allowed_variants", "category", "ru_rows", "kk_coverage"]

PROMPT = """You build a terminology glossary for the Kazakh localization of the mobile RP game "Grand Mobile".
You get rows (key, ru, en, kk). Extract GAME TERMS only: factions/organizations, family (семья = отбасы),
business, property, vehicles (incl. slang like "фура"), currencies and items (Grand Coins, "ГК"),
game mechanics, punishments and moderation (бан, варн, мут, джайл), jobs, ranks, events, UI section names.
Skip ordinary words, whole sentences, numbers and placeholders.

For each term return the base (dictionary) form:
- ru: Russian term in nominative singular, lowercase unless proper name
- kk: how THIS file translates it (dictionary form, without case endings); if the file uses several, the most common
- kk_variants: other kk translations seen in these rows (comma-separated, may be "")
- en: English term from en rows ("" if unclear)
- category: faction | family | business | property | vehicle | currency | item | mechanic | punishment | job | rank | event | ui | other
- comment: short note in Russian (slang, abbreviation, brand that is not translated), may be ""
Return each term once per batch."""

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {k: {"type": "string"} for k in ("ru", "kk", "kk_variants", "en", "category", "comment")},
                "required": ["ru", "kk", "kk_variants", "en", "category", "comment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["terms"],
    "additionalProperties": False,
}


def stem(word: str, n: int = 5) -> str:
    w = word.strip().lower()
    return w if len(w) <= n else w[:n]


WORD = re.compile(r"[\wёәғқңөұүһі]+")


def contains_stem(text: str, term: str) -> bool:
    """Каждое слово термина — начало какого-то слова текста (по основе из первых 5 букв).

    Только начало слова: иначе короткие термины («Ци», «тир») находятся внутри «акция», «квартира».
    Слова до 3 букв сравниваются целиком.
    """
    text_words = WORD.findall(text.lower())
    words = WORD.findall(term.lower())
    if not words:
        return False
    for w in words:
        if len(w) <= 3:
            ok = w in text_words
        else:
            ok = any(t.startswith(stem(w)) for t in text_words)
        if not ok:
            return False
    return True


def build(ctx, llm: LLM) -> list[dict]:
    keys = [k for k in ctx.order if re.search(r"[а-яё]", ctx.ru.get(k, ""), re.I) and k in ctx.kk]
    users = []
    for i in range(0, len(keys), CHUNK):
        rows = [{"key": k, "ru": ctx.ru[k], "en": ctx.en.get(k, ""), "kk": ctx.kk[k]} for k in keys[i : i + CHUNK]]
        users.append(json.dumps(rows, ensure_ascii=False))

    seen = Counter()
    kk_votes: dict[str, Counter] = defaultdict(Counter)
    meta: dict[str, dict] = {}
    for res in llm.complete_many(PROMPT, users, SCHEMA):
        for t in (res or {}).get("terms", []):
            ru = t["ru"].strip()
            if not ru:
                continue
            k = ru.lower()
            seen[k] += 1
            for v in [t["kk"], *t["kk_variants"].split(",")]:
                if v.strip():
                    kk_votes[k][v.strip()] += 1 + (v == t["kk"])
            m = meta.setdefault(k, {"ru": ru, "en": "", "category": "", "comment": ""})
            for f in ("en", "category", "comment"):
                if not m[f] and t[f].strip():
                    m[f] = t[f].strip()

    out = []
    for k, m in meta.items():
        if not kk_votes[k]:
            continue
        kk, *rest = [v for v, _ in kk_votes[k].most_common()]
        ru_rows = [key for key in keys if contains_stem(ctx.ru[key], m["ru"])]
        if len(ru_rows) < 2:
            continue
        covered = sum(contains_stem(ctx.kk[key], kk) for key in ru_rows)
        out.append({
            **m,
            "kk": kk,
            "allowed_variants": ", ".join(rest),
            "ru_rows": len(ru_rows),
            "kk_coverage": round(covered / len(ru_rows), 2),
        })
    return sorted(out, key=lambda r: -r["ru_rows"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m locqa.glossary_draft")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ref", help="intl_en.arb")
    p.add_argument("--out", default="glossary_draft.csv")
    a = p.parse_args(argv)
    llm = LLM()
    if not llm.enabled:
        print("Нет ключа API (OPENAI_API_KEY или GEMINI_API_KEY): черновик глоссария требует LLM", file=sys.stderr)
        return 1
    rows = build(build_context(a.source, a.target, en=a.ref), llm)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{a.out}: {len(rows)} терминов; LLM: {llm.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
