"""Дозаполнение MT двумя моделями: Gemma смотрит непроверенные строки, Qwen перепроверяет её находки.

Находка принимается, только если её подтвердили обе модели. Вердикты пишутся в кэш под именем
модели "ensemble" (подключается через LOCQA_FALLBACK_CACHE=gpt-5.4:low,ensemble:low).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa._load import build_context  # noqa: E402
from locqa.checks import llm_checks as lc  # noqa: E402
from locqa.llm import LLM, _wrap_schema, row_context  # noqa: E402
from locqa.suggest import glossary_hits  # noqa: E402

FIRST = os.environ.get("FIRST_MODEL", "ollama/gemma3:27b")
SECOND = os.environ.get("SECOND_MODEL", "ollama/qwen3:32b")
NONE = {"kind": "none", "fragment": "", "problem": "", "suggestion": "", "confidence": 0.0}
ign = lc.DETECTION_CACHE_IGNORE


def flagged(a, kk):
    kind, frag = a.get("kind"), (a.get("fragment") or "").strip()
    return (kind in lc.MT_THRESHOLD and float(a.get("confidence", 0)) >= lc.MT_THRESHOLD[kind]
            and frag and frag.lower() in kk.lower())


ctx = build_context("data/intl_ru.arb", "data/intl_kk.arb", en="data/intl_en.arb", uz="data/intl_uz.arb",
                    glossary="glossary.csv")
index = {k: i for i, k in enumerate(ctx.order)}
items = []
for key in lc.mt_candidates(ctx):
    row = row_context(ctx, key, index)
    row["glossary"] = glossary_hits(ctx, row["ru"])
    items.append(row)

schema = _wrap_schema(lc.MT_SCHEMA)
ref = LLM(model="gpt-5.4", effort="low", offline=True)
store = LLM(model="ensemble", effort="low", offline=True)
missing = [it for it in items if ref._item_cache_get(lc.MT_PROMPT, schema, it, ign) is None]
print(f"непроверенных строк: {len(missing)} из {len(items)}", flush=True)

first = LLM(model=FIRST, workers=4, batch_size=5)
ans1 = {a["id"]: a for a in first.ask(missing, lc.MT_PROMPT, lc.MT_SCHEMA, cache_ignore=ign)}
hits = [it for it in missing if it["id"] in ans1 and flagged(ans1[it["id"]], it["kk"])]
print(f"{FIRST}: ответ по {len(ans1)}, находок {len(hits)}", flush=True)

second = LLM(model=SECOND, workers=4, batch_size=5)
ans2 = {a["id"]: a for a in second.ask(hits, lc.MT_PROMPT, lc.MT_SCHEMA, cache_ignore=ign)}
confirmed = {it["id"] for it in hits if it["id"] in ans2 and flagged(ans2[it["id"]], it["kk"])}
print(f"{SECOND}: подтвердила {len(confirmed)} из {len(hits)}", flush=True)

saved = 0
for it in missing:
    i = it["id"]
    if i not in ans1 or (i in {h["id"] for h in hits} and i not in ans2):
        continue  # нет вердикта — строка остаётся непроверенной, отчёт покажет complete=false
    store._item_cache_put(lc.MT_PROMPT, schema, it, ans1[i] if i in confirmed else NONE, 0.0, ign)
    saved += 1
print(f"сохранено вердиктов: {saved}", flush=True)
