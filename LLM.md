# LLM-часть locqa (Человек 2)

| Модуль | Что делает |
|---|---|
| `locqa/llm.py` | `LLM.ask(items, prompt, item_schema)`: батчи, JSON по схеме, кэш на каждую строку в `.locqa_cache/items/`, учёт токенов и стоимости (`summary()`), остановка после 3 ответов «нет денег» подряд. Провайдеры: OpenAI, Gemini, Ollama |
| `locqa/checks/llm_checks.py` | `check(ctx, llm, skip_keys)` — находки для отчёта: `length_overflow` и `machine_translation_suspect` (калька). `check_with_meaning()` дополнительно отдаёт ошибки смысла для носителей |
| `locqa/checks/signals.py` | `check(ctx)` без LLM: потерянные и подменённые имена, несовпадающие числа |
| `locqa/suggest.py` | `suggest(ctx, findings, llm)`: варианты исправлений с проверкой кодом (плейсхолдеры, длина кнопок, аффикс после `{…}`, КАПС) |
| `locqa/sheet.py` | экспорт находок в CSV для Google Таблиц (3 части) и импорт решений в `decisions.csv` для `fix.py` |
| `locqa/glossary_draft.py` | черновик глоссария через LLM |

## Команды

```bash
pip install -e ".[dev]"
locqa check --source data/intl_ru.arb --target data/intl_kk.arb --en data/intl_en.arb --uz data/intl_uz.arb \
  --glossary glossary.csv --out out/report.json --review-dir out/review
```

Режимы: без флагов — с LLM, `--offline` — только ответы из кэша, `--no-llm` — только кодовые проверки.
Рядом с отчётом пишется `report.llm.json`: токены, стоимость, полнота проверки и статистика исправлений.
Ошибки «другой смысл» в ТЗ не описаны, поэтому в `report.json` они не идут, но попадают в таблицы ревью.

```bash
python scripts/run_uz.py                  # бонус: кодовая часть для узбекского
python -m pytest
```

## Разметка носителями

`python scripts/build_review_site.py` собирает `out/review_site/review.html`: один файл, открывается двойным кликом, сервер не нужен, прогресс хранится в браузере. Проверяющий выбирает свою часть, отмечает строки кнопками или клавишами 1–4 и скачивает `review_A_done.csv`.

Этот файл принимают обе команды:
```bash
python -m locqa.sheet import review_A_done.csv review_B_done.csv review_C_done.csv --source data/intl_ru.arb
python scripts/precision_sample.py score review_A_done.csv
```

В файле тексты кейса: передавать только внутри команды, не выкладывать в интернет.

## Настройки

Ключи — в `.env` (не попадает в git). `OPENAI_API_KEY`, `GEMINI_API_KEY`.

| Переменная | Смысл |
|---|---|
| `LOCQA_MODEL` | `gpt-5.4`, `gemini-*`, `ollama/<модель>` |
| `LOCQA_EFFORT` | глубина для reasoning-моделей, по умолчанию `low` |
| `LOCQA_OFFLINE=1` | только кэш |
| `LOCQA_FALLBACK_CACHE` | брать ответы других моделей из кэша: `ensemble:low,ollama/gemma3:27b:low` |
| `LOCQA_WORKERS`, `LOCQA_BATCH` | параллельность и размер батча в `locqa check` |
| `LOCQA_PRICE` | своя цена: `in,out,cached`, $ за 1M |
| `OLLAMA_BASE_URL` | адрес Ollama |

Локальная модель: окно контекста должно быть больше 4096 (`OLLAMA_CONTEXT_LENGTH=16384`, см. `ollama/Modelfile`), иначе промпт молча обрезается.
