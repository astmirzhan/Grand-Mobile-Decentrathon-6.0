"""Пошаговая проверка LLM: ключ -> доступные модели -> один маленький запрос через LLM.ask.

    .venv/bin/python scripts/llm_smoke.py [модель]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa.llm import DEFAULT_MODEL, LLM, has_credentials  # noqa: E402  (.env грузится при импорте)

model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
print("1) ключ:", "есть" if has_credentials(model) else "НЕТ — положите OPENAI_API_KEY в .env")
if not has_credentials(model):
    sys.exit(1)

import openai  # noqa: E402

ids = sorted(m.id for m in openai.OpenAI().models.list() if m.id.startswith(("gpt-4", "gpt-5", "o3", "o4")))
print("2) доступные модели:", ", ".join(ids))
if model not in ids:
    print(f"   модели {model} нет в списке, выберите другую: LOCQA_MODEL=... или аргумент")
    sys.exit(1)

llm = LLM(model=model, cache_dir=".locqa_cache/smoke", workers=1)
schema = {"type": "object", "properties": {"kk": {"type": "string"}}, "required": ["kk"]}
res = llm.ask([{"id": "1", "ru": "Купить"}, {"id": "2", "ru": "Семья"}],
              "Translate each ru into Kazakh (Cyrillic). Return one result per item.", schema)
print("3) ответ:", res)
print("   usage:", llm.summary())
sys.exit(0 if len(res) == 2 else 1)
