import json

import pytest

from locqa.llm import ITEMS_MARKER, LLM
from locqa.models import Context


def make_ctx(rows: dict[str, tuple[str, str]], en: dict[str, str] | None = None, glossary=None) -> Context:
    """rows: key -> (ru, kk)."""
    return Context(
        ru={k: v[0] for k, v in rows.items()},
        kk={k: v[1] for k, v in rows.items() if v[1] is not None},
        en=en or {},
        order=list(rows),
        sections={k: "TEST" for k in rows},
        glossary=glossary or [],
    )


def fake_llm(answer, tmp_path, **kw) -> tuple[LLM, list]:
    """answer(item, system) -> dict | None. Возвращает (LLM, журнал вызовов)."""
    calls = []

    def call(system, user, schema):
        calls.append((system, user))
        items = json.loads(user.split(ITEMS_MARKER, 1)[1])
        results = []
        for it in items:
            r = answer(it, system)
            if r is not None:
                results.append({"id": it["id"], **r})
        return {"results": results}, {"input_tokens": 1000, "output_tokens": 100}

    return LLM(call=call, cache_dir=tmp_path / "cache", workers=1, **kw), calls


@pytest.fixture
def ctx_factory():
    return make_ctx
