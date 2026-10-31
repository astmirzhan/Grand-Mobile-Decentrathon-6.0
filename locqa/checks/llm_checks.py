"""Смысловые проверки: length_overflow и machine_translation_suspect.

length_overflow: кандидатов отбирает код, LLM подтверждает и предлагает короткий вариант.
Без LLM в отчёт идут только кандидаты с повторяющимся дописанным хвостом (детерминированное доказательство).

machine_translation_suspect: только LLM. В отчёт идёт находка, если confidence ≥ порога
и указанный LLM «кривой фрагмент» действительно есть в kk (проверка кодом от галлюцинаций).
"""
from __future__ import annotations

import re

from ..llm import LLM, get_llm, row_context
from ..models import Context, Finding
from ..suggest import BASE_RULES, UI_TOKENS, glossary_hits, key_tokens, match_case, validate

LENGTH_RATIO = 1.6
LENGTH_MIN_DIFF = 6
# Казахский по природе длиннее русского, но не длиннее узбекского (оба тюркские):
# если uz есть, kk должен быть длиннее и его, иначе это нормальная морфология.
REF_RATIO = 1.5
LENGTH_CONFIDENCE = 0.6
MT_CONFIDENCE = 0.8
MT_MIN_WORDS = 1
# для проверок глоссарий — только подсказка: правка глоссария не должна сбрасывать оплаченные ответы
DETECTION_CACHE_IGNORE = ("glossary",)
CYRILLIC = re.compile(r"[а-яёәғқңөұүһі]", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\{\w+\}")


def _visible(text: str) -> str:
    return PLACEHOLDER.sub("", text).strip()


def length_candidates(ctx: Context) -> list[tuple[str, float]]:
    """(ключ, kk/ru) для коротких элементов интерфейса, где kk заметно длиннее ru (и uz, если он есть)."""
    out = []
    for key in ctx.order:
        ru, kk = ctx.ru.get(key, ""), ctx.kk.get(key, "")
        if not ru or not kk or kk == ru:
            continue
        ui = bool(key_tokens(key) & UI_TOKENS) or len(ru.split()) <= 3
        if not ui:
            continue
        ratio = len(kk) / len(ru)
        if ratio <= LENGTH_RATIO or len(kk) - len(ru) < LENGTH_MIN_DIFF:
            continue
        uz = ctx.uz.get(key, "")
        if len(_visible(uz)) >= 3 and len(kk) / len(uz) <= REF_RATIO:
            continue
        out.append((key, ratio))
    return out


def recurring_tails(ctx: Context, keys: list[str], min_words: int = 3, max_words: int = 6) -> dict[str, str]:
    """Ключ -> хвост, если один и тот же хвост из ≥ min_words слов дописан к ≥ 2 кандидатам с разным ru.

    Нормальный перевод так не выглядит: у разных коротких строк («Победа», «РАЗНОЕ») нет общего смысла,
    значит общий хвост в kk — лишний текст. Сигнал детерминированный и не зависит от LLM.
    """
    found: dict[str, str] = {}
    for n in range(max_words, min_words - 1, -1):  # сначала самые длинные хвосты
        groups: dict[str, list[str]] = {}
        for key in keys:
            words = ctx.kk[key].split()
            if len(words) > n and key not in found:
                groups.setdefault(" ".join(words[-n:]).lower(), []).append(key)
        for tail, ks in groups.items():
            # общее слово в ru («Купить авто?» / «Купить дом?») — хвост может быть его переводом
            stems = [{w[:4] for w in re.findall(r"\w+", ctx.ru[k].lower())} for k in ks]
            if len(ks) >= 2 and not set.intersection(*stems):
                for k in ks:
                    found[k] = " ".join(ctx.kk[k].split()[-n:])
    return found


LENGTH_PROMPT = (
    BASE_RULES
    + """

Task: each item is a candidate for "length_overflow" — the kk text is much longer than ru (see "ratio").
IMPORTANT: Kazakh is naturally 1.3-2x longer than Russian because of agglutinative morphology and
analytic constructions ("до начала" -> "басталуына дейін", "Внимание" -> "Назар аударыңыз" are NORMAL).
Natural length is NOT a problem. Compare with uz (another Turkic language) and en: they show the normal length.
The problem is kk containing EXTRA words whose meaning is absent from ru/en/uz: an appended explanation,
call to action or tail (like "...in order to get full information", "...click to go to the section",
"...enable and continue"), or a whole sentence where ru is one word.
Decide:
- is_short_ui: is this a short UI element (button, tab, title, label, badge)? Use en, the key name and neighbors.
- kind: "padding" if kk = a correct translation of ru plus extra words; "wrong_meaning" if kk means something
  different from ru (a translation of another string, wrong sense) — that is a different problem, not length;
  "ok" if the length is natural.
- extra_words: the exact extra fragment copied verbatim from kk whose meaning is not in ru/en/uz, "" if none.
- too_long: true only if extra_words is non-empty or kk is clearly padded compared to uz and en.
- short_kk: kk without the extra words (natural Kazakh, placeholders unchanged), "" if too_long is false.
- confidence: 0..1 that this is a real length_overflow problem. Normal morphology -> below 0.3.
- reason: one short sentence in Russian for the reviewer."""
)
LENGTH_SCHEMA = {
    "type": "object",
    "properties": {
        "is_short_ui": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["padding", "wrong_meaning", "ok"]},
        "extra_words": {"type": "string"},
        "too_long": {"type": "boolean"},
        "short_kk": {"type": "string"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["is_short_ui", "kind", "extra_words", "too_long", "short_kk", "confidence", "reason"],
}


def check_length_overflow(ctx: Context, llm: LLM | None = None) -> list[Finding]:
    llm = llm or get_llm()
    cands = length_candidates(ctx)
    index = {k: i for i, k in enumerate(ctx.order)}

    def base(key: str, ratio: float) -> Finding:
        ru, kk = ctx.ru[key], ctx.kk[key]
        return Finding(
            key=key,
            issue_type="length_overflow",
            severity="high" if key_tokens(key) & {"button", "btn", "tab"} else "medium",
            source=ru,
            target=kk,
            evidence=f"kk длиннее ru в {ratio:.1f} раза ({len(kk)} против {len(ru)} симв.) для короткого элемента интерфейса",
            suggestion=None,
            confidence=0.5,
        )

    tails = recurring_tails(ctx, [k for k, _ in cands])

    def by_tail(key: str, ratio: float) -> Finding:
        f = base(key, ratio)
        tail = tails[key]
        n = sum(t.lower() == tail.lower() for t in tails.values())
        f.confidence = 0.85
        f.evidence += f"; одинаковый хвост «{tail}» дописан к {n} разным коротким строкам"
        short = match_case(f.source, f.target, f.target[: f.target.rfind(tail)].strip())
        if validate(f.source, f.target, short, "length_overflow", key) is None:
            f.suggestion = short
        return f

    if not llm.enabled:
        # без LLM в отчёт идут только доказанные случаи; длина сама по себе — не доказательство
        return [by_tail(k, r) for k, r in cands if k in tails]

    def f_kk(key: str) -> str:
        return ctx.kk.get(key, "")

    items = []
    for key, ratio in cands:
        row = row_context(ctx, key, index)
        row["ratio"] = round(ratio, 2)
        row["glossary"] = glossary_hits(ctx, row["ru"])
        items.append(row)
    answers = {r["id"]: r for r in llm.ask(items, LENGTH_PROMPT, LENGTH_SCHEMA, cache_ignore=DETECTION_CACHE_IGNORE)}

    findings = []
    for key, ratio in cands:
        a = answers.get(key)
        if a is None:  # LLM не ответил по строке: остаётся только кодовое доказательство
            if key in tails:
                findings.append(by_tail(key, ratio))
            continue
        conf = float(a.get("confidence", 0))
        extra = (a.get("extra_words") or "").strip()
        # лишний фрагмент обязан реально быть в kk — защита от выдуманных объяснений
        # wrong_meaning — не длина: такие строки ловит проверка machine_translation_suspect
        confirmed = (
            a.get("kind") == "padding" and a.get("is_short_ui") and a.get("too_long") and conf >= LENGTH_CONFIDENCE
            and extra and extra.lower() in f_kk(key).lower()
        )
        if not confirmed:
            # LLM иногда пропускает строку или путает её с wrong_meaning;
            # повторяющийся хвост — независимое доказательство дописанного текста
            if key in tails:
                findings.append(by_tail(key, ratio))
            continue
        f = base(key, ratio)
        f.confidence = round(conf, 2)
        f.evidence += f"; лишнее: «{extra}»"
        if a.get("reason"):
            f.evidence += f". LLM: {a['reason']}"
        short = match_case(f.source, f.target, (a.get("short_kk") or "").strip())
        if short and validate(f.source, f.target, short, "length_overflow", key) is None:
            f.suggestion = short
        findings.append(f)
    return findings


MT_PROMPT = (
    BASE_RULES
    + """

Context: this file was translated by professional human translators and is mostly correct. A small number of
strings were later corrupted. Your job is to find the CORRUPTED strings, not to improve style.
The translators' house style (free translation, their word choices, their loanwords, a whole section written
in a slightly different style) is NOT an error — if you would merely phrase it differently, do not flag.

Flag only these two kinds:
- "wrong_meaning": kk clearly says something different from ru (check with en and uz): a translation of another
  string, an antonym or unrelated word, a different brand/name/number, a wrong sense of an ambiguous Russian
  word ("Брак" marriage -> "defect"), meaning lost so a player would be misled.
- "calque": kk is a broken word-by-word machine translation from Russian that a native speaker would find
  ungrammatical or confusing (Russian word order that breaks Kazakh grammar, case government copied from
  Russian, a Russian idiom translated literally into nonsense). Merely "could be more natural" is NOT a calque.
Not this problem: spelling typos and wrong letters, capitalization, punctuation, length, glossary preferences.
Expect at most 1-2 corrupted strings per batch; usually zero.

For each item return:
- kind: "wrong_meaning", "calque" or "none".
- fragment: the exact wrong fragment copied verbatim from kk ("" if none).
- problem: one short sentence in Russian: what exactly is wrong (what kk says vs what ru says).
- suggestion: the whole corrected kk string (placeholders unchanged), "" if none.
- confidence: 0..1 that a native speaker reviewer would agree this string is corrupted."""
)
MT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["wrong_meaning", "calque", "none"]},
        "fragment": {"type": "string"},
        "problem": {"type": "string"},
        "suggestion": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "fragment", "problem", "suggestion", "confidence"],
}
# Строка-обрывок: продолжение подставляет код («Купить за» + цена, «Заключение от» + имя).
# Жалоба LLM на «пропущенное» здесь ложная; другой смысл («до» -> «қазір») остаётся находкой.
_RU_PREPOSITIONS = set("от до в во на с со за по через к ко из у о об при для и или".split())
_OMISSION = re.compile(r"потер|пропущ|пропал|только|нет слова|не хватает|обрыв|неполн|опущен", re.IGNORECASE)


def is_fragment(ru: str) -> bool:
    words = ru.strip().lower().split()
    return ru != ru.rstrip() or (bool(words) and words[-1] in _RU_PREPOSITIONS)


MT_KIND_LABEL = {"wrong_meaning": "другой смысл", "calque": "калька"}
# калька — более спорный вид, порог выше
MT_THRESHOLD = {"wrong_meaning": MT_CONFIDENCE, "calque": 0.9}


def mt_candidates(ctx: Context, skip_keys: set[str] | frozenset = frozenset()) -> list[str]:
    out = []
    for key in ctx.order:
        ru, kk = ctx.ru.get(key, ""), ctx.kk.get(key, "")
        if key in skip_keys or not kk or kk == ru or not CYRILLIC.search(kk):
            continue
        # однобуквенные сокращения («ч» -> «с» = сағат) смыслом не проверить — только шум
        if len(_visible(kk).split()) < MT_MIN_WORDS or len(_visible(kk)) < 2:
            continue
        out.append(key)
    return out


def check_machine_translation(
    ctx: Context, llm: LLM | None = None, skip_keys: set[str] | frozenset = frozenset()
) -> list[Finding]:
    """skip_keys — ключи, на которые уже есть находки других проверок (экономим запросы)."""
    llm = llm or get_llm()
    if not llm.enabled:
        return []
    index = {k: i for i, k in enumerate(ctx.order)}
    items = []
    for key in mt_candidates(ctx, skip_keys):
        row = row_context(ctx, key, index)
        row["glossary"] = glossary_hits(ctx, row["ru"])
        items.append(row)

    findings = []
    for a in llm.ask(items, MT_PROMPT, MT_SCHEMA, cache_ignore=DETECTION_CACHE_IGNORE):
        key = a["id"]
        conf = float(a.get("confidence", 0))
        fragment = (a.get("fragment") or "").strip()
        kk = ctx.kk[key]
        kind = a.get("kind")
        if kind not in MT_THRESHOLD or conf < MT_THRESHOLD[kind] or not fragment or fragment.lower() not in kk.lower():
            continue
        if is_fragment(ctx.ru[key]) and _OMISSION.search(a.get("problem") or ""):
            continue
        cand = match_case(ctx.ru[key], kk, (a.get("suggestion") or "").strip())
        findings.append(
            Finding(
                key=key,
                issue_type="machine_translation_suspect",
                severity="low",
                source=ctx.ru[key],
                target=kk,
                evidence=f"{MT_KIND_LABEL[kind]}, «{fragment}»: {a.get('problem', '').strip()}",
                suggestion=cand if validate(ctx.ru[key], kk, cand, "machine_translation_suspect", key) is None else None,
                confidence=round(conf, 2),
            )
        )
    order = {k: i for i, k in enumerate(ctx.order)}
    return sorted(findings, key=lambda f: order.get(f.key, 0))


def is_meaning_finding(f: Finding) -> bool:
    return f.issue_type == "machine_translation_suspect" and f.evidence.startswith(MT_KIND_LABEL["wrong_meaning"])


def check_with_meaning(
    ctx: Context, llm: LLM | None = None, skip_keys: set[str] | frozenset = frozenset()
) -> tuple[list[Finding], list[Finding]]:
    """(находки для report.json, ошибки смысла для носителей).

    В ТЗ machine_translation_suspect — калька и русская грамматика, отдельного типа «другой смысл» нет.
    Такие находки реальны и полезны для исправлений, но в отчёт по типам не идут.
    """
    length = check_length_overflow(ctx, llm)
    mt = check_machine_translation(ctx, llm, skip_keys | {f.key for f in length})
    return length + [f for f in mt if not is_meaning_finding(f)], [f for f in mt if is_meaning_finding(f)]


def check(ctx: Context, llm: LLM | None = None, skip_keys: set[str] | frozenset = frozenset()) -> list[Finding]:
    """Единая точка входа по контракту check(ctx) -> list[Finding]."""
    return check_with_meaning(ctx, llm, skip_keys)[0]
