from conftest import fake_llm, make_ctx

from locqa.llm import LLM, _wrap_schema, row_context

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_batches_and_maps_by_id(tmp_path):
    llm, calls = fake_llm(lambda it, s: {"ok": it["id"] != "3"}, tmp_path, batch_size=2)
    items = [{"id": str(i)} for i in range(5)]
    res = llm.ask(items, "P", SCHEMA)
    assert len(calls) == 3
    assert {r["id"]: r["ok"] for r in res} == {"0": True, "1": True, "2": True, "3": False, "4": True}


def test_cache_makes_second_run_free(tmp_path):
    llm, calls = fake_llm(lambda it, s: {"ok": True}, tmp_path)
    items = [{"id": "a"}]
    llm.ask(items, "P", SCHEMA)
    cost = llm.usage["cost_usd"]
    llm2, calls2 = fake_llm(lambda it, s: {"ok": False}, tmp_path)
    assert llm2.ask(items, "P", SCHEMA) == [{"id": "a", "ok": True}]
    assert calls2 == []
    assert llm2.usage["cached_items"] == 1 and llm2.usage["cost_usd"] == 0
    assert llm2.usage["cost_usd_total"] == cost > 0


def test_unknown_ids_dropped(tmp_path):
    llm = LLM(call=lambda s, u, sc: ({"results": [{"id": "zzz"}, {"id": "a", "ok": True}]}, {}),
              cache_dir=tmp_path, workers=1)
    assert llm.ask([{"id": "a"}], "P", SCHEMA) == [{"id": "a", "ok": True}]


def test_split_on_truncation(tmp_path):
    def call(system, user, schema):
        import json
        items = json.loads(user.split(":", 1)[1])
        if len(items) > 1:
            return None, {"stop_reason": "max_tokens"}
        return {"results": [{"id": items[0]["id"], "ok": True}]}, {}

    llm = LLM(call=call, cache_dir=tmp_path, workers=1)
    assert len(llm.ask([{"id": str(i)} for i in range(4)], "P", SCHEMA)) == 4


def test_no_split_on_api_error(tmp_path):
    n = []
    llm = LLM(call=lambda s, u, sc: (n.append(1), (None, {}))[1], cache_dir=tmp_path, workers=1)
    assert llm.ask([{"id": str(i)} for i in range(4)], "P", SCHEMA) == []
    assert len(n) == 1 and llm.usage["failed_requests"] == 1


def test_disabled_returns_nothing(tmp_path):
    llm = LLM(enabled=False, cache_dir=tmp_path)
    assert llm.ask([{"id": "a"}], "P", SCHEMA) == []
    assert llm.summary()["enabled"] is False


def test_wrap_schema_adds_id():
    s = _wrap_schema(SCHEMA)
    item = s["properties"]["results"]["items"]
    assert item["required"][0] == "id" and item["additionalProperties"] is False


def test_row_context_neighbors():
    ctx = make_ctx({f"k{i}": (f"ru{i}", f"kk{i}") for i in range(10)}, en={"k5": "en5"})
    row = row_context(ctx, "k5")
    assert row["en"] == "en5" and row["section"] == "TEST"
    assert [n["key"] for n in row["neighbors"]] == ["k2", "k3", "k4", "k6", "k7", "k8"]


def _openai_resp(content, finish="stop", refusal=None):
    from types import SimpleNamespace as NS
    usage = NS(prompt_tokens=1000, completion_tokens=50, total_tokens=1050, prompt_tokens_details=NS(cached_tokens=400))
    msg = NS(content=content, refusal=refusal)
    return NS(id="r1", model="gpt-4.1-2025-04-14", usage=usage, choices=[NS(finish_reason=finish, message=msg)])


class _FakeOpenAI:
    def __init__(self, resp):
        self.kwargs = None
        outer = self

        class _C:
            def create(self, **kw):
                outer.kwargs = kw
                return resp

        self.chat = type("Chat", (), {"completions": _C()})()


def test_openai_call_parses_usage_and_json(tmp_path):
    llm = LLM(model="gpt-4.1", cache_dir=tmp_path, enabled=True, workers=1)
    llm._client = fake = _FakeOpenAI(_openai_resp('{"results": [{"id": "a", "ok": true}]}'))
    assert llm.ask([{"id": "a"}], "P", SCHEMA) == [{"id": "a", "ok": True}]
    assert fake.kwargs["temperature"] == 0
    assert fake.kwargs["response_format"]["json_schema"]["strict"] is True
    assert llm.usage["input_tokens"] == 600 and llm.usage["cache_read_input_tokens"] == 400
    assert round(llm.usage["cost_usd"], 6) == round((600 * 2 + 50 * 8 + 400 * 0.5) / 1e6, 6)


def test_openai_reasoning_model_uses_effort(tmp_path):
    llm = LLM(model="gpt-5", effort="low", cache_dir=tmp_path, enabled=True, workers=1)
    llm._client = fake = _FakeOpenAI(_openai_resp('{"results": []}'))
    llm.ask([{"id": "a"}], "P", SCHEMA)
    assert fake.kwargs["reasoning_effort"] == "low" and "temperature" not in fake.kwargs


def test_openai_truncated_is_splittable(tmp_path):
    llm = LLM(model="gpt-4.1", cache_dir=tmp_path, enabled=True, workers=1)
    llm._client = _FakeOpenAI(_openai_resp(None, finish="length"))
    assert llm._complete_ex("P", "u", {})[0] is None
    assert llm._complete_ex("P", "u", {})[1] is True


def test_glossary_stem_matches_word_start_only():
    from locqa.glossary_draft import contains_stem
    assert contains_stem("Получите награды за задания", "награда")
    assert not contains_stem("Новая акция в магазине", "Ци")
    assert not contains_stem("Ваша квартира", "тир")
    assert contains_stem("Зайдите в тир", "тир")


def test_quota_abort_stops_network_but_keeps_cache(tmp_path):
    import openai
    from types import SimpleNamespace as NS

    llm, _ = fake_llm(lambda it, s: {"ok": True}, tmp_path, model="gpt-4.1", batch_size=1)
    llm.ask([{"id": "a", "ru": "a"}], "P", SCHEMA)  # ответ в кэше

    class _Quota:
        n = 0

        def create(self, **kw):
            _Quota.n += 1
            resp = NS(status_code=429, headers={}, request=None)
            raise openai.RateLimitError("no credits", response=resp,
                                        body={"type": "insufficient_quota", "code": "credit_balance_exhausted"})

    llm2 = LLM(model="gpt-4.1", cache_dir=tmp_path / "cache", enabled=True, workers=1, batch_size=1)
    llm2._client = type("C", (), {"chat": type("Chat", (), {"completions": _Quota()})()})()
    llm2.workers = 1
    res = llm2.ask([{"id": x, "ru": x} for x in "abcdef"], "P", SCHEMA)
    assert res == [{"id": "a", "ok": True}]  # из кэша
    s = llm2.summary()
    assert _Quota.n == 3 and "insufficient_quota" in s["aborted"]  # после 3 отказов подряд сеть не трогаем
    assert s["complete"] is False and s["items_answered"] == 1 and s["items_asked"] == 6


def test_item_cache_survives_rebatching(tmp_path):
    llm, calls = fake_llm(lambda it, s: {"ok": True}, tmp_path, batch_size=3)
    items = [{"id": f"k{i}", "ru": f"t{i}"} for i in range(9)]
    llm.ask(items, "P", SCHEMA)
    assert len(calls) == 3
    llm2, calls2 = fake_llm(lambda it, s: {"ok": True}, tmp_path, batch_size=3)
    res = llm2.ask(items[:4] + [{"id": "new", "ru": "x"}] + items[4:], "P", SCHEMA)
    assert len(res) == 10 and len(calls2) == 1  # спросили только новую строку
    assert llm2.summary()["cost_usd_total"] == llm.summary()["cost_usd_total"] + llm2.summary()["cost_usd"]


def test_gemini_request_shape(tmp_path, monkeypatch):
    from locqa.llm import provider_of
    assert provider_of("gemini-3.8-flash") == "gemini"
    llm = LLM(model="gemini-3.8-flash", effort="low", cache_dir=tmp_path, enabled=True, workers=1)
    llm._client = fake = _FakeOpenAI(_openai_resp('{"results": []}'))
    llm.ask([{"id": "a"}], "P", SCHEMA)
    assert fake.kwargs["reasoning_effort"] == "low"
    assert "temperature" not in fake.kwargs and "prompt_cache_key" not in fake.kwargs


def test_offline_uses_cache_only(tmp_path):
    llm, _ = fake_llm(lambda it, s: {"ok": True}, tmp_path)
    llm.ask([{"id": "a", "ru": "a"}], "P", SCHEMA)
    calls = []
    off = LLM(call=lambda *a: calls.append(a) or ({"results": []}, {}), cache_dir=tmp_path / "cache",
              offline=True, workers=1)
    res = off.ask([{"id": "a", "ru": "a"}, {"id": "b", "ru": "b"}], "P", SCHEMA)
    assert res == [{"id": "a", "ok": True}] and calls == []
    assert off.summary()["complete"] is False and "офлайн" in off.summary()["aborted"]


def test_ollama_request_shape(tmp_path):
    from locqa.llm import has_credentials, provider_of
    assert provider_of("ollama/gemma3:12b") == "ollama" and has_credentials("ollama/gemma3:12b")
    llm = LLM(model="ollama/gemma3:12b", cache_dir=tmp_path, workers=1)
    llm._client = fake = _FakeOpenAI(_openai_resp('{"results": []}'))
    llm.ask([{"id": "a"}], "P", SCHEMA)
    assert fake.kwargs["model"] == "gemma3:12b" and fake.kwargs["temperature"] == 0
    assert llm.summary()["cost_usd"] == 0


def test_fallback_cache_asks_only_missing_rows(tmp_path, monkeypatch):
    llm, _ = fake_llm(lambda it, s: {"ok": True}, tmp_path, model="gpt-5.4", effort="low")
    llm.ask([{"id": "a", "ru": "a"}], "P", SCHEMA)
    monkeypatch.setenv("LOCQA_FALLBACK_CACHE", "ollama/x:27b:low,gpt-5.4:low")  # в имени модели бывает двоеточие
    local, calls = fake_llm(lambda it, s: {"ok": False}, tmp_path, model="ollama/gemma3:27b")
    res = {r["id"]: r["ok"] for r in local.ask([{"id": "a", "ru": "a"}, {"id": "b", "ru": "b"}], "P", SCHEMA)}
    assert res == {"a": True, "b": False} and len(calls) == 1
    assert local.usage["fallback_items"] == 1
