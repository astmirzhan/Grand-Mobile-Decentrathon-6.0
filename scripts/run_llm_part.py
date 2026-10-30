"""Сквозной прогон LLM-части на реальных данных: проверки -> одна находка на ключ -> suggest -> отчёт -> таблица ревью.

Проверки Человека 1 ещё не готовы, поэтому здесь временные заглушки (untranslated, wrong_language,
same_as_source, placeholder_mismatch) и resolve. Проверки Человека 3 — настоящие: locqa.checks.kazakh.

    .venv/bin/python scripts/run_llm_part.py            # с моделью (догружает недостающее)
    .venv/bin/python scripts/run_llm_part.py --offline  # без модели: только оплаченные ответы из кэша
    .venv/bin/python scripts/run_llm_part.py --no-llm   # совсем без LLM: только кодовые сигналы
"""
import argparse
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa._load import build_context  # noqa: E402
from locqa.checks import kazakh, llm_checks, signals  # noqa: E402
from locqa.llm import LLM  # noqa: E402
from locqa.models import Finding  # noqa: E402
from locqa.sheet import export  # noqa: E402
from locqa.suggest import placeholders, suggest  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
OUT = "out"
PRIORITY = [
    "untranslated", "wrong_language", "same_as_source", "placeholder_mismatch", "plural_mismatch",
    "suffix_harmony", "orthography", "glossary_violation", "inconsistent_term", "length_overflow",
    "machine_translation_suspect",
]


def is_latin_text(text: str) -> bool:
    """Весь текст латиницей (не меньше 4 букв): «Avtorizatsiya xatosi»."""
    letters = [c for c in re.sub(r"\{\w+\}", "", text) if c.isalpha()]
    return len(letters) >= 4 and not any("а" <= c.lower() <= "я" or c.lower() in "ёәғқңөұүһі" for c in letters)


def stand_in_basic(ctx) -> list[Finding]:
    """Временная замена checks/basic.py (Человек 1)."""
    out = []
    for k in ctx.order:
        ru, kk = ctx.ru[k], ctx.kk.get(k)
        if k == "currencySymbol":
            continue
        if not kk or not kk.strip():
            out.append(Finding(k, "untranslated", "high", ru, kk or "", "ключа нет в kk или значение пустое", None, 1.0))
        elif kk == ctx.uz.get(k) and kk != ru:
            out.append(Finding(k, "wrong_language", "high", ru, kk, "kk дословно совпадает с uz", None, 0.95))
        elif re.search(r"[а-яё]", ru, re.I) and is_latin_text(kk):
            out.append(Finding(k, "wrong_language", "high", ru, kk, "ru кириллицей, а kk целиком латиницей", None, 0.9))
        elif kk == ru and len(re.findall(r"[а-яё]+", ru, re.I)) >= 2 and ru != ctx.en.get(k):
            out.append(Finding(k, "same_as_source", "high", ru, kk, "kk совпадает с ru (≥ 2 русских слова)", None, 0.9))
        elif placeholders(ru) != placeholders(kk):
            out.append(Finding(k, "placeholder_mismatch", "high", ru, kk,
                               f"плейсхолдеры ru {sorted(placeholders(ru))} ≠ kk {sorted(placeholders(kk))}", None, 1.0))
    return out


def resolve(findings: list[Finding]) -> list[Finding]:
    """Временная замена resolve.py: одна находка на ключ по приоритету типов."""
    best: dict[str, Finding] = {}
    for f in findings:
        cur = best.get(f.key)
        rank = (PRIORITY.index(f.issue_type), -f.confidence, f.suggestion is None)
        if cur is None or rank < (PRIORITY.index(cur.issue_type), -cur.confidence, cur.suggestion is None):
            best[f.key] = f
    return list(best.values())


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="только ответы из кэша, без запросов к API")
    mode.add_argument("--no-llm", action="store_true", help="без LLM совсем")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    ctx = build_context("data/intl_ru.arb", "data/intl_kk.arb", en="data/intl_en.arb", uz="data/intl_uz.arb",
                        glossary="glossary.csv")
    llm = LLM(workers=int(os.environ.get("LOCQA_WORKERS", 8)), batch_size=int(os.environ.get("LOCQA_BATCH", 25)),
              offline=args.offline or None, enabled=False if args.no_llm else None)
    t = time.time()

    basic = stand_in_basic(ctx)
    print(f"заглушки простых проверок: {len(basic)}")
    lang = kazakh.check(ctx)
    print(f"казахские проверки (Человек 3): {len(lang)}")
    sig = signals.check(ctx)
    print(f"кодовые сигналы (имена, числа): {len(sig)}")
    # resolve оставит по ключу одну находку; LLM всё равно проверяет и ключи из сигналов —
    # так её ответ может дать исправление там, где у сигнала его нет
    llm_found, meaning = llm_checks.check_with_meaning(ctx, llm, skip_keys={f.key for f in basic})
    print(f"LLM-проверки: {len(llm_found)}, ошибки смысла: {len(meaning)} "
          f"({time.time() - t:.0f}s, ${llm.summary()['cost_usd_total']:.2f})")

    findings = resolve(basic + lang + sig + llm_found)
    taken = {f.key for f in findings}
    meaning = [f for f in resolve(meaning) if f.key not in taken]
    stats = suggest(ctx, findings + meaning, llm)
    print(f"suggest: {stats}")

    order = {k: i for i, k in enumerate(ctx.order)}
    findings.sort(key=lambda f: order.get(f.key, 0))
    review = findings + meaning  # носители видят и ошибки смысла
    review.sort(key=lambda f: order.get(f.key, 0))
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f.issue_type] = by_type.get(f.issue_type, 0) + 1
    report = {
        "summary": {"total": len(findings), "by_type": by_type, "meaning_review": len(meaning),
                    "llm": llm.summary(), "suggest": stats},
        "findings": [f.to_dict() for f in findings],
    }
    with open(f"{OUT}/report_llm.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    with open(f"{OUT}/report_meaning.json", "w", encoding="utf-8") as fh:
        json.dump([f.to_dict() for f in meaning], fh, ensure_ascii=False, indent=1)
    paths = export(ctx, review, f"{OUT}/review")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print("файлы:", f"{OUT}/report_llm.json", *map(str, paths))


if __name__ == "__main__":
    main()
