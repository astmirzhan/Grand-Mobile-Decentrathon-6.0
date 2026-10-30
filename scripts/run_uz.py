"""Бонус: кодовая часть проверки узбекского файла (без LLM).

    .venv/bin/python scripts/run_uz.py

Проверяет то, что не зависит от языка: пропуски, копии ru, плейсхолдеры, числа, дописанные хвосты.
Смысловые проверки и орфография для узбекского требуют модели и языкового профиля lang/uz.py.
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa._load import build_context  # noqa: E402
from locqa.checks import llm_checks, signals  # noqa: E402
from locqa.llm import LLM  # noqa: E402
from locqa.models import Finding  # noqa: E402
from locqa.suggest import placeholders  # noqa: E402

# kk здесь — второй свидетель для брендов: signals сравнивает цель с ctx.uz
ctx = build_context("data/intl_ru.arb", "data/intl_uz.arb", en="data/intl_en.arb", uz="data/intl_kk.arb")
found = []
for k in ctx.order:
    ru, tr = ctx.ru[k], ctx.kk.get(k)
    if k == "currencySymbol":
        continue
    if not tr or not tr.strip():
        found.append(Finding(k, "untranslated", "high", ru, tr or "", "ключа нет в uz или значение пустое", None, 1.0))
    elif tr == ru and len(re.findall(r"[а-яё]+", ru, re.I)) >= 2 and ru != ctx.en.get(k):
        found.append(Finding(k, "same_as_source", "high", ru, tr, "uz совпадает с ru (≥ 2 русских слова)", None, 0.9))
    elif placeholders(ru) != placeholders(tr):
        found.append(Finding(k, "placeholder_mismatch", "high", ru, tr,
                             f"плейсхолдеры ru {sorted(placeholders(ru))} ≠ uz {sorted(placeholders(tr))}", None, 1.0))
taken = {f.key for f in found}
# brand_mismatch рассчитан на кириллицу: в латинском узбекском Jackpot -> Jekpot выглядел бы потерей имени
found += [f for f in signals.number_mismatch(ctx) if f.key not in taken]
taken = {f.key for f in found}
found += [f for f in llm_checks.check_length_overflow(ctx, LLM(enabled=False)) if f.key not in taken]
by_type = collections.Counter(f.issue_type for f in found)
os.makedirs("out", exist_ok=True)
with open("out/report_uz.json", "w", encoding="utf-8") as fh:
    json.dump({"summary": {"total": len(found), "by_type": dict(by_type), "llm": "выключен"},
               "findings": [f.to_dict() for f in found]}, fh, ensure_ascii=False, indent=1)
print(f"out/report_uz.json: {len(found)} находок {dict(by_type)}")
for f in found[:10]:
    print(f"  {f.issue_type[:12]:12} {f.key[:30]:30} {f.source[:28]!r} -> {f.target[:28]!r}")
