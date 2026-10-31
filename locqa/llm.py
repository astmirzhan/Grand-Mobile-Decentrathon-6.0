"""Обёртка над LLM API: батчи, кэш на диске, учёт токенов и стоимости.

Провайдер выбирается по модели: gpt-*/o* — OpenAI, gemini-* — Gemini, ollama/* — локальная модель.
Ключ берётся из окружения или из файла .env (OPENAI_API_KEY / GEMINI_API_KEY).
Без ключа обёртка выключена: ask() возвращает [], программа работает дальше.
Повторяемость: temperature=0 там, где модель его принимает, и кэш
(ключ = sha256 от модели, промпта и данных) — повторный прогон бесплатный и одинаковый.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .models import Context

log = logging.getLogger(__name__)


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export ").strip(), v.strip().strip("\"'"))


_load_dotenv()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("LOCQA_MODEL") or (
    "gemini-3.8-flash" if os.environ.get("GEMINI_API_KEY") and not os.environ.get("OPENAI_API_KEY")
    else "gpt-5.4"
)
# low: на A/B по length_overflow gpt-5.4 с low точнее gpt-4.1 при цене ~$0.12 за проверку
DEFAULT_EFFORT = os.environ.get("LOCQA_EFFORT", "low")

# $ за 1M токенов: input, output, запись в кэш, чтение из кэша.
# Цены OpenAI сверить на https://openai.com/api/pricing; свои можно задать в LOCQA_PRICE="in,out,cached".
PRICES = {
    "gemini": (0.0, 0.0, 0.0, 0.0),  # бесплатный тариф Google AI Studio; на платном задать LOCQA_PRICE
    "ollama/": (0.0, 0.0, 0.0, 0.0),  # локальная модель
    "gpt-5.5": (5.00, 30.00, 5.00, 0.50),
    "gpt-5.4": (2.50, 15.00, 2.50, 0.25),
    "gpt-5.4-mini": (0.75, 4.50, 0.75, 0.075),
    "gpt-4.1": (2.00, 8.00, 2.00, 0.50),
    "gpt-4.1-mini": (0.40, 1.60, 0.40, 0.10),
    "gpt-4o": (2.50, 10.00, 2.50, 1.25),
    "gpt-5": (1.25, 10.00, 1.25, 0.125),
    "gpt-5-mini": (0.25, 2.00, 0.25, 0.025),
}

ITEMS_MARKER = "ITEMS (JSON):"
QUOTA_ABORT_AFTER = 3

# call(system, user, schema) -> (data | None, usage dict)
CallFn = Callable[[str, str, dict], "tuple[dict | None, dict]"]


def provider_of(model: str) -> str:
    if model.startswith("ollama/"):  # локальная модель: ollama/gemma3:12b
        return "ollama"
    return "gemini" if model.startswith("gemini") else "openai"


def is_reasoning_model(model: str) -> bool:
    """Reasoning-модели OpenAI не принимают temperature, зато принимают reasoning_effort."""
    return model.startswith(("o1", "o3", "o4", "gpt-5"))


def has_credentials(model: str = DEFAULT_MODEL) -> bool:
    if provider_of(model) == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if provider_of(model) == "ollama":
        return True  # ключ не нужен; если сервер не запущен, первый запрос даст ошибку соединения
    return bool(os.environ.get("OPENAI_API_KEY"))


def _price(model: str) -> tuple[float, float, float, float]:
    if os.environ.get("LOCQA_PRICE"):
        p_in, p_out, p_cr = (float(x) for x in os.environ["LOCQA_PRICE"].split(","))
        return p_in, p_out, p_in, p_cr
    for name in sorted(PRICES, key=len, reverse=True):  # "gpt-4.1-2025-04-14" -> "gpt-4.1"
        if model.startswith(name):
            return PRICES[name]
    log.warning("Нет цены для модели %s — стоимость будет 0, задайте LOCQA_PRICE", model)
    return (0.0, 0.0, 0.0, 0.0)


def _cost(model: str, u: dict) -> float:
    p_in, p_out, p_cw, p_cr = _price(model)
    return (
        u.get("input_tokens", 0) * p_in
        + u.get("output_tokens", 0) * p_out
        + u.get("cache_creation_input_tokens", 0) * p_cw
        + u.get("cache_read_input_tokens", 0) * p_cr
    ) / 1_000_000


class LLM:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        cache_dir: str | Path = ".locqa_cache",
        batch_size: int = 25,
        workers: int = 4,
        enabled: bool | None = None,
        call: CallFn | None = None,
        offline: bool | None = None,
    ):
        self.model = model
        self.effort = effort
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self.workers = workers
        self._call = call
        self.provider = provider_of(model)
        self.fallback_cache = [
            tuple(x.rsplit(":", 1)) for x in os.environ.get("LOCQA_FALLBACK_CACHE", "").split(",") if ":" in x
        ]
        self._temperature_ok = not is_reasoning_model(model)
        self.enabled = (call is not None or has_credentials(model)) if enabled is None else enabled
        self._client = None
        self._lock = threading.Lock()
        # причина остановки сети (нет денег, неверный ключ): дальше работаем только из кэша
        self.aborted: str | None = None
        # офлайн: только готовые ответы из кэша, в API не ходим (LOCQA_OFFLINE=1)
        self.offline = os.environ.get("LOCQA_OFFLINE") == "1" if offline is None else offline
        if self.offline and enabled is not False:
            self.enabled = True
            self.aborted = "офлайн-режим: только ответы из кэша"
        self._quota_errors = 0  # подряд; OpenAI выдаёт insufficient_quota и прерывисто, при почти нулевом балансе
        self.usage = {
            "items_asked": 0,  # строк отправлено на проверку
            "items_answered": 0,  # строк, по которым пришёл ответ; меньше asked = проверка неполная
            "requests": 0,  # реальные запросы к API в этом прогоне
            "cached_requests": 0,  # ответы на батч из кэша
            "cached_items": 0,  # строки, взятые из кэша строк
            "fallback_items": 0,  # из них ответы другой модели (смешанный отчёт — указать в методологии)
            "failed_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": 0.0,  # потрачено в этом прогоне
            "cost_usd_total": 0.0,  # с учётом ответов из кэша (полная цена пайплайна)
        }

    # ---- публичный интерфейс ----

    def ask(self, items: list[dict], prompt: str, item_schema: dict, batch_size: int | None = None,
            cache_ignore: tuple[str, ...] = ()) -> list[dict]:
        """Отдаёт items батчами, возвращает по одному результату на item (сопоставление по "id").

        item_schema описывает объект-ответ на один item; поле "id" добавляется само.
        Items без ответа (отказ, ошибка API) просто отсутствуют в результате.
        cache_ignore — поля item, которые не входят в ключ кэша (подсказки, не меняющие ответ).
        """
        if not self.enabled or not items:
            return []
        schema = _wrap_schema(item_schema)
        by_id = {str(it["id"]): it for it in items}
        answered: dict[str, dict] = {}
        todo = []
        # кэш по строке: не зависит от того, как строки разложены по батчам,
        # поэтому новые находки других проверок не заставляют переспрашивать старые строки
        for id_, it in by_id.items():
            hit = self._item_cache_get(prompt, schema, it, cache_ignore)
            if hit is None:
                todo.append(it)
            else:
                answered[id_] = {**hit, "id": id_}
        size = batch_size or self.batch_size
        batches = [todo[i : i + size] for i in range(0, len(todo), size)]
        for batch, (res, cost) in zip(batches, self._map(lambda b: self._ask_batch(b, prompt, schema), batches)):
            got = {str(r.get("id")): r for r in res if str(r.get("id")) in by_id}
            for id_, r in got.items():
                answered.setdefault(id_, r)
                self._item_cache_put(prompt, schema, by_id[id_], r, cost / max(1, len(got)), cache_ignore)
        with self._lock:
            self.usage["items_asked"] += len(by_id)
            self.usage["items_answered"] += len(answered)
            self.usage["cached_items"] += len(by_id) - len(todo)
        return list(answered.values())

    def complete_many(self, system: str, users: list[str], schema: dict) -> list[dict | None]:
        """Произвольные запросы с JSON-ответом по схеме; порядок результатов = порядок users."""
        if not self.enabled:
            return [None] * len(users)
        return list(self._map(lambda u: self._complete(system, u, schema), users))

    def summary(self) -> dict:
        u = dict(self.usage)
        u["cost_usd"] = round(u["cost_usd"], 4)
        u["cost_usd_total"] = round(u["cost_usd_total"], 4)
        complete = self.enabled and not self.aborted and u["items_answered"] == u["items_asked"]
        return {"enabled": self.enabled, "complete": complete, "aborted": self.aborted,
                "provider": self.provider, "model": self.model, "effort": self.effort, **u}

    # ---- внутреннее ----

    def _map(self, fn, seq):
        if self.workers <= 1 or len(seq) <= 1:
            return map(fn, seq)
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(fn, seq))

    def _ask_batch(self, batch: list[dict], prompt: str, schema: dict) -> tuple[list[dict], float]:
        """(результаты, стоимость запроса)."""
        user = ITEMS_MARKER + "\n" + json.dumps(batch, ensure_ascii=False, indent=1)
        data, splittable, cost = self._complete_ex(prompt, user, schema)
        if data is None and splittable and len(batch) > 1:
            # ответ обрезан (max_tokens) или отказ на весь батч: делим пополам, чтобы не терять строки
            mid = len(batch) // 2
            (r1, c1), (r2, c2) = self._ask_batch(batch[:mid], prompt, schema), self._ask_batch(batch[mid:], prompt, schema)
            return r1 + r2, cost + c1 + c2
        return (data or {}).get("results", []), cost

    def _item_path(self, prompt: str, schema: dict, item: dict, ignore: tuple[str, ...] = (),
                   model: str | None = None, effort: str | None = None) -> Path:
        stable = {k: v for k, v in item.items() if k != "id" and k not in ignore}
        key = hashlib.sha256(
            json.dumps([model or self.model, effort or self.effort, prompt, schema, stable],
                       ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return self.cache_dir / "items" / key[:2] / f"{key}.json"

    def _item_cache_get(self, prompt: str, schema: dict, item: dict, ignore: tuple[str, ...] = ()) -> dict | None:
        path = self._item_path(prompt, schema, item, ignore)
        if not path.exists():
            # ответы более сильной модели: дозаполняем только то, чего у неё нет (LOCQA_FALLBACK_CACHE=gpt-5.4:low)
            for model, effort in self.fallback_cache:
                other = self._item_path(prompt, schema, item, ignore, model=model, effort=effort)
                if other.exists():
                    path = other
                    with self._lock:
                        self.usage["fallback_items"] += 1
                    break
            else:
                return None
        cached = json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            self.usage["cost_usd_total"] += cached.get("cost_usd", 0.0)
        return cached["data"]

    def _item_cache_put(self, prompt: str, schema: dict, item: dict, result: dict, cost: float,
                        ignore: tuple[str, ...] = ()) -> None:
        path = self._item_path(prompt, schema, item, ignore)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"data": result, "cost_usd": cost}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _complete(self, system: str, user: str, schema: dict) -> dict | None:
        return self._complete_ex(system, user, schema)[0]

    def _complete_ex(self, system: str, user: str, schema: dict) -> tuple[dict | None, bool, float]:
        """(данные, можно ли повторить по частям, стоимость). Ошибки API по частям не повторяем."""
        if not self.enabled:
            return None, False, 0.0
        key = hashlib.sha256(
            json.dumps([self.model, self.effort, system, user, schema], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                self.usage["cached_requests"] += 1
                self.usage["cost_usd_total"] += cached.get("cost_usd", 0.0)
            return cached["data"], False, cached.get("cost_usd", 0.0)
        if self.aborted:  # сеть остановлена — без ответа, но и без новых платных попыток
            with self._lock:
                self.usage["failed_requests"] += 1
            return None, False, 0.0

        data, usage = (self._call or self._openai_call)(system, user, schema)
        cost = _cost(usage.get("model", self.model), usage)
        with self._lock:
            self.usage["requests"] += 1
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                self.usage[k] += usage.get(k, 0)
            self.usage["cost_usd"] += cost
            self.usage["cost_usd_total"] += cost
            if data is None:
                self.usage["failed_requests"] += 1
        if data is not None:  # неудачи не кэшируем, чтобы повторный прогон их перезапросил
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"data": data, "cost_usd": cost}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return data, usage.get("stop_reason") in ("max_tokens", "refusal"), cost

    def _abort(self, reason: str) -> None:
        with self._lock:
            if not self.aborted:
                self.aborted = reason
                log.error("LLM остановлен: %s. Готовые ответы в кэше; после исправления перезапустите прогон", reason)

    def _openai_call(self, system: str, user: str, schema: dict) -> tuple[dict | None, dict]:
        import openai

        gemini = self.provider == "gemini"
        local = self.provider == "ollama"
        model = self.model.removeprefix("ollama/")
        if self._client is None:
            if gemini:  # Gemini через OpenAI-совместимый адрес Google
                self._client = openai.OpenAI(
                    api_key=os.environ["GEMINI_API_KEY"], base_url=GEMINI_BASE_URL, max_retries=5, timeout=300
                )
            elif local:  # Ollama на этой машине: данные никуда не уходят
                self._client = openai.OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL, max_retries=1, timeout=900)
            else:
                self._client = openai.OpenAI(max_retries=5)
        kwargs: dict = {}
        if local:
            kwargs.update(temperature=0, seed=0)
        elif gemini:
            # Gemini 3 думает всегда; Google не советует снижать temperature (модель может зациклиться)
            kwargs["reasoning_effort"] = self.effort
        else:
            # одинаковый системный промпт -> один ключ: OpenAI чаще попадает в свой кэш промптов
            kwargs["prompt_cache_key"] = hashlib.sha256(system.encode()).hexdigest()[:32]
            if is_reasoning_model(self.model):
                kwargs["reasoning_effort"] = self.effort
            elif self._temperature_ok:
                kwargs.update(temperature=0, seed=0)
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "locqa", "schema": schema, "strict": True},
                },
                # локальная модель без лимита может крутить один ответ минутами
                max_completion_tokens=4000 if local else 16000,
                **kwargs,
            )
        except openai.BadRequestError as e:
            if "temperature" in str(e.message) and self._temperature_ok:
                self._temperature_ok = False  # модель не принимает temperature — повторяем без него
                return self._openai_call(system, user, schema)
            log.warning("LLM: ошибка API 400: %s", e.message)
            return None, {}
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            self._abort(f"нет доступа к API: {e.message}")
            return None, {}
        except openai.APIStatusError as e:
            # бывает code=insufficient_quota, а бывает type=insufficient_quota, code=credit_balance_exhausted
            # 402 — у Gemini «prepayment credits are depleted»
            if e.status_code == 402 or "insufficient_quota" in (e.code, e.type) or e.code == "credit_balance_exhausted":
                with self._lock:
                    self._quota_errors += 1
                    n = self._quota_errors
                log.warning("LLM: OpenAI ответил insufficient_quota (%d подряд)", n)
                if n >= QUOTA_ABORT_AFTER:
                    self._abort("на счету OpenAI закончились деньги (insufficient_quota)")
            else:
                log.warning("LLM: ошибка API %s: %s", e.status_code, e.message)
            return None, {}
        except openai.APIConnectionError as e:
            log.warning("LLM: нет соединения: %s", e)
            return None, {}

        with self._lock:
            self._quota_errors = 0
        u = resp.usage
        cached = (u.prompt_tokens_details.cached_tokens or 0) if u and u.prompt_tokens_details else 0
        usage = {
            "model": self.model if local else resp.model,  # Ollama отдаёт имя без префикса ollama/
            "input_tokens": (u.prompt_tokens - cached) if u else 0,
            # Gemini не включает «размышления» в completion_tokens, но они есть в total_tokens
            "output_tokens": max(u.completion_tokens or 0, (u.total_tokens or 0) - (u.prompt_tokens or 0)) if u else 0,
            "cache_read_input_tokens": cached,
        }
        choice = resp.choices[0]
        if choice.finish_reason != "stop" or choice.message.refusal:
            usage["stop_reason"] = "max_tokens" if choice.finish_reason == "length" else "refusal"
            log.warning("LLM: finish_reason=%s refusal=%s", choice.finish_reason, choice.message.refusal)
            return None, usage
        try:
            return json.loads(choice.message.content or ""), usage
        except json.JSONDecodeError:
            log.warning("LLM: невалидный JSON (%s)", resp.id)
            return None, usage


def _wrap_schema(item_schema: dict) -> dict:
    item = json.loads(json.dumps(item_schema))
    item.setdefault("type", "object")
    item.setdefault("additionalProperties", False)
    item["properties"] = {"id": {"type": "string"}, **item.get("properties", {})}
    item["required"] = ["id"] + [r for r in item.get("required", list(item["properties"])) if r != "id"]
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
        "additionalProperties": False,
    }


# ---- общий экземпляр: CLI настраивает его флагом --llm ----

_default: LLM | None = None


def configure(**kwargs) -> LLM:
    global _default
    _default = LLM(**kwargs)
    return _default


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM(enabled=False)  # пока CLI не включил --llm, сеть не трогаем
    return _default


# ---- контекст строки для промптов ----


def _clip(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[:n] + "…"


def row_context(ctx: Context, key: str, index: dict[str, int] | None = None, neighbors: int = 3) -> dict:
    """key, раздел, description, ru, en, kk и по 3 соседних ключа сверху и снизу."""
    if index is None:
        index = {k: i for i, k in enumerate(ctx.order)}
    row = {
        "id": key,
        "key": key,
        "section": ctx.sections.get(key, ""),
        "ru": ctx.ru.get(key, ""),
        "en": ctx.en.get(key, ""),
        "kk": ctx.kk.get(key, ""),
    }
    if ctx.uz.get(key):
        row["uz"] = ctx.uz[key]  # второй тюркский язык: ориентир по смыслу и нормальной длине
    if ctx.descriptions.get(key):
        row["description"] = ctx.descriptions[key]
    i = index.get(key)
    if i is not None and neighbors:
        near = ctx.order[max(0, i - neighbors) : i] + ctx.order[i + 1 : i + 1 + neighbors]
        row["neighbors"] = [{"key": k, "ru": _clip(ctx.ru.get(k, "")), "kk": _clip(ctx.kk.get(k, ""))} for k in near]
    return row
