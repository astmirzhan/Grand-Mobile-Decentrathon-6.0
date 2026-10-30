"""LLM-based QA checks: length overflow and machine translation detection."""
from __future__ import annotations

import re
from typing import Any

from locqa.llm import LLM, get_llm, row_context
from locqa.models import Context, Finding, compute_severity

MT_THRESHOLD = {"calque": 0.9, "wrong_meaning": 0.95}
DETECTION_CACHE_IGNORE = ("section", "description", "neighbors")

LENGTH_PROMPT = """Analyze if the Kazakh translation (kk) is too long for a short UI element (button, title, badge).
Identify padding words (extra explanatory words) that can be safely removed.
Return:
- is_short_ui: true if this is a short UI element (button, tab, title)
- too_long: true if kk is unnaturally long compared to ru
- short_kk: compact, natural Kazakh translation
- extra_words: the exact words in kk that are redundant/padding
- confidence: 0.0 to 1.0
- reason: short explanation in Russian"""

LENGTH_SCHEMA = {
    "type": "object",
    "properties": {
        "is_short_ui": {"type": "boolean"},
        "too_long": {"type": "boolean"},
        "short_kk": {"type": "string"},
        "extra_words": {"type": "string"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["is_short_ui", "too_long", "short_kk", "extra_words", "confidence", "reason"],
}

MT_PROMPT = """Analyze the Kazakh translation (kk) for machine translation artifacts or semantic errors.
Do NOT suggest stylistic improvements if the translation is natural and correct.
Look for:
- 'calque': unnatural literal translation of Russian idioms or phrases (Russian syntactic structure in Kazakh)
- 'wrong_meaning': critical mistranslation that changes the meaning
Return:
- kind: 'calque' | 'wrong_meaning' | 'none'
- fragment: the exact fragment from kk containing the error
- problem: description of the issue in Russian
- suggestion: corrected Kazakh text
- confidence: 0.0 to 1.0"""

MT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["calque", "wrong_meaning", "none"]},
        "fragment": {"type": "string"},
        "problem": {"type": "string"},
        "suggestion": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "fragment", "problem", "suggestion", "confidence"],
}


def length_candidates(ctx: Any) -> list[tuple[str, float]]:
    """Identifies short UI keys where kk is significantly longer than ru."""
    candidates: list[tuple[str, float]] = []
    order = getattr(ctx, "order", list(ctx.ru.keys()))
    uz_dict = getattr(ctx, "uz", {})

    for key in order:
        if key not in ctx.ru or key not in ctx.kk:
            continue
        ru = ctx.ru[key].strip()
        kk = ctx.kk[key].strip()

        if not ru or not kk:
            continue
        if len(ru) > 30:
            continue

        diff = len(kk) - len(ru)
        ratio = len(kk) / len(ru)

        if diff < 6 or ratio <= 1.6:
            continue

        # If Uzbek translation exists, check if it's also long (normal morphology)
        uz = uz_dict.get(key, "").strip()
        if uz and len(uz) > 0:
            if len(kk) / len(uz) <= 1.5:
                continue

        candidates.append((key, ratio))

    return candidates


def recurring_tails(ctx: Any, keys: list[str]) -> dict[str, str]:
    """Finds repeated multi-word tails (>= 3 words) appended to strings without shared Russian words."""
    tails_map: dict[str, list[str]] = {}

    for k in keys:
        kk = ctx.kk.get(k, "").strip()
        words = kk.split()
        if len(words) >= 4:
            for n_words in range(3, min(len(words), 8)):
                tail = " ".join(words[-n_words:])
                tails_map.setdefault(tail, []).append(k)

    # Filter tails shared by at least 2 keys that DO NOT share significant Russian words
    valid_tails: dict[str, str] = {}
    for tail, key_list in sorted(tails_map.items(), key=lambda item: len(item[0]), reverse=True):
        # Filter pairs that have no common Russian words
        unrelated_keys = []
        for i, k1 in enumerate(key_list):
            ru1_words = {w.lower() for w in re.findall(r"[а-яёА-ЯЁa-zA-Z]{3,}", ctx.ru.get(k1, ""))}
            for k2 in key_list[i + 1:]:
                ru2_words = {w.lower() for w in re.findall(r"[а-яёА-ЯЁa-zA-Z]{3,}", ctx.ru.get(k2, ""))}
                if not (ru1_words & ru2_words):
                    if k1 not in unrelated_keys:
                        unrelated_keys.append(k1)
                    if k2 not in unrelated_keys:
                        unrelated_keys.append(k2)

        if len(unrelated_keys) >= 2:
            for k in unrelated_keys:
                if k not in valid_tails:
                    valid_tails[k] = tail

    return valid_tails


def check_length_overflow(ctx: Any, llm: LLM | None = None) -> list[Finding]:
    """Detects UI strings with excessive length or repetitive padding."""
    llm = llm or get_llm()
    cands = length_candidates(ctx)
    if not cands:
        return []

    cand_keys = [k for k, _ in cands]
    findings: list[Finding] = []

    # 1. Without LLM: check for recurring tails
    tails = recurring_tails(ctx, cand_keys)
    if not llm.enabled:
        for k, tail in tails.items():
            kk = ctx.kk[k]
            shortened = kk[:-len(tail)].strip()
            findings.append(
                Finding(
                    key=k,
                    issue_type="length_overflow",
                    severity=compute_severity("length_overflow", key=k),
                    source=ctx.ru[k],
                    target=kk,
                    evidence=f"Повторяющийся хвост: '{tail}'",
                    suggestion=shortened,
                    confidence=0.85,
                )
            )
        return findings

    # 2. With LLM: evaluate candidate strings
    index = {k: i for i, k in enumerate(getattr(ctx, "order", list(ctx.ru.keys())))}
    items = [row_context(ctx, k, index) for k in cand_keys]

    results = llm.ask(items, LENGTH_PROMPT, LENGTH_SCHEMA)
    for res in results:
        k = res.get("id")
        if not k or k not in ctx.kk:
            continue

        kk = ctx.kk[k]
        is_short_ui = res.get("is_short_ui", False)
        too_long = res.get("too_long", False)
        extra_words = res.get("extra_words", "").strip()
        short_kk = res.get("short_kk", "").strip()
        confidence = float(res.get("confidence", 0.0))
        reason = res.get("reason", "")

        if is_short_ui and too_long and extra_words and extra_words in kk and short_kk:
            findings.append(
                Finding(
                    key=k,
                    issue_type="length_overflow",
                    severity=compute_severity("length_overflow", key=k),
                    source=ctx.ru[k],
                    target=kk,
                    evidence=reason,
                    suggestion=short_kk,
                    confidence=confidence,
                )
            )

    return findings


def mt_candidates(ctx: Any, skip_keys: set[str] | None = None) -> list[str]:
    """Selects strings to check for machine translation / semantic errors."""
    order = getattr(ctx, "order", list(ctx.ru.keys()))
    skip = skip_keys or set()
    return [k for k in order if k in ctx.ru and k in ctx.kk and k not in skip]


def _run_mt_queries(ctx: Any, llm: LLM, skip_keys: set[str] | None = None) -> list[tuple[dict, Finding]]:
    skip = skip_keys or set()
    keys = mt_candidates(ctx, skip_keys=skip)
    if not keys:
        return []

    index = {k: i for i, k in enumerate(getattr(ctx, "order", list(ctx.ru.keys())))}
    items = [row_context(ctx, k, index) for k in keys]

    results = llm.ask(items, MT_PROMPT, MT_SCHEMA, cache_ignore=DETECTION_CACHE_IGNORE)
    validated: list[tuple[dict, Finding]] = []

    for res in results:
        k = res.get("id")
        if not k or k not in ctx.kk:
            continue

        kind = res.get("kind")
        frag = (res.get("fragment") or "").strip()
        prob = res.get("problem", "")
        sugg = res.get("suggestion", "")
        conf = float(res.get("confidence", 0.0))

        if kind not in MT_THRESHOLD or conf < MT_THRESHOLD[kind]:
            continue

        kk = ctx.kk[k]
        if not frag or frag.lower() not in kk.lower():
            continue

        # Check for omission complaints in wrong_meaning:
        # e.g. fragment is the whole translation and suggestion adds the missing particle back
        if kind == "wrong_meaning":
            if sugg.startswith(frag) and len(sugg) > len(kk):
                continue

        f = Finding(
            key=k,
            issue_type="machine_translation_suspect",
            severity="low",
            source=ctx.ru[k],
            target=kk,
            evidence=prob,
            suggestion=sugg,
            confidence=conf,
            fragment=frag,
        )
        validated.append((res, f))

    return validated


def check_machine_translation(ctx: Any, llm: LLM | None = None, skip_keys: set[str] | None = None) -> list[Finding]:
    """Runs MT checks and returns all confirmed findings."""
    llm = llm or get_llm()
    if not llm.enabled:
        return []
    items = _run_mt_queries(ctx, llm, skip_keys=skip_keys)
    return [f for _, f in items]


def check_with_meaning(ctx: Any, llm: LLM | None = None, skip_keys: set[str] | None = None) -> tuple[list[Finding], list[Finding]]:
    """Runs MT checks, separating calques (report) from semantic errors (meaning)."""
    llm = llm or get_llm()
    if not llm.enabled:
        return [], []

    items = _run_mt_queries(ctx, llm, skip_keys=skip_keys)
    report: list[Finding] = []
    meaning: list[Finding] = []

    for res, f in items:
        if res.get("kind") == "wrong_meaning":
            meaning.append(f)
        else:
            report.append(f)

    return report, meaning


def check(ctx: Any, llm: LLM | None = None) -> list[Finding]:
    """Entry point for all LLM-based checks."""
    llm = llm or get_llm()
    length_findings = check_length_overflow(ctx, llm)
    report_mt, _ = check_with_meaning(ctx, llm)
    return length_findings + report_mt
