"""Сравнение модели с эталонными ответами gpt-5.4 из кэша на одних и тех же строках MT.

    .venv/bin/python scripts/eval_local.py ollama/gemma3:12b 100

Эталон — находки gpt-5.4 (не истина, но лучшее, что есть без ручной разметки):
совпало = нашли обе, лишнее = нашла только проверяемая модель, пропущено = нашла только gpt-5.4.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa._load import build_context  # noqa: E402
from locqa.checks import llm_checks as lc  # noqa: E402
from locqa.llm import LLM, row_context  # noqa: E402
from locqa.suggest import glossary_hits  # noqa: E402

model = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
batch = int(sys.argv[3]) if len(sys.argv) > 3 else 10

ctx = build_context("data/intl_ru.arb", "data/intl_kk.arb", en="data/intl_en.arb", uz="data/intl_uz.arb",
                    glossary="glossary.csv")
index = {k: i for i, k in enumerate(ctx.order)}
items = []
for key in lc.mt_candidates(ctx):
    row = row_context(ctx, key, index)
    row["glossary"] = glossary_hits(ctx, row["ru"])
    items.append(row)

ref = LLM(model="gpt-5.4", effort="low", offline=True)
ref_ans = {a["id"]: a for a in ref.ask(items, lc.MT_PROMPT, lc.MT_SCHEMA, cache_ignore=lc.DETECTION_CACHE_IGNORE)}
items = [it for it in items if it["id"] in ref_ans][:n]  # только строки, где эталон есть


def flagged(a, kk):
    kind, frag = a.get("kind"), (a.get("fragment") or "").strip()
    return (kind in lc.MT_THRESHOLD and float(a.get("confidence", 0)) >= lc.MT_THRESHOLD[kind]
            and frag and frag.lower() in kk.lower())


gold = {it["id"] for it in items if flagged(ref_ans[it["id"]], it["kk"])}
llm = LLM(model=model, workers=int(os.environ.get("LOCQA_WORKERS", 1)), batch_size=batch)
t = time.time()
ans = {a["id"]: a for a in llm.ask(items, lc.MT_PROMPT, lc.MT_SCHEMA, cache_ignore=lc.DETECTION_CACHE_IGNORE)}
got = {it["id"] for it in items if it["id"] in ans and flagged(ans[it["id"]], it["kk"])}
dt = time.time() - t
print(f"{model}: {len(items)} строк, ответ по {len(ans)}, {dt:.0f}s ({dt / max(1, len(items)):.1f}s/строку)")
print(f"gpt-5.4 нашёл {len(gold)}, модель нашла {len(got)}: совпало {len(gold & got)}, "
      f"лишнее {len(got - gold)}, пропущено {len(gold - got)}")
for k in sorted(got | gold, key=index.get):
    mark = "=" if k in got and k in gold else ("+" if k in got else "-")
    a = ans.get(k) or ref_ans[k]
    print(f"  {mark} {k}: {ctx.ru[k][:35]!r} -> {ctx.kk[k][:35]!r} | {a.get('kind')} {a.get('problem', '')[:70]}")
