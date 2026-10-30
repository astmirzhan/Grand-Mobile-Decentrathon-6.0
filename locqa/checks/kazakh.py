"""Kazakh language QA checks: orthography, suffix harmony, glossary consistency."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from locqa import glossary as gl
from locqa.lang import kk as kk_lang
from locqa.models import Context, Finding, compute_severity

# Regex for placeholder with attached suffix, e.g. {price}-ге or {provider}ға
_SUFFIXES_SORTED = sorted({re.escape(s) for s in kk_lang.SUFFIXES}, key=len, reverse=True)
_AFFIX_AFTER_PH = re.compile(
    r"\{(\w+)\}(-?(" + "|".join(_SUFFIXES_SORTED) + r"))(?![а-яәғқңөұүһіa-z0-9])",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def rephrase_without_affix(text: str) -> str | None:
    """
    Rewrites a sentence so a placeholder with an affix stands alone after a colon.
    Returns None if:
    - text contains HTML/XML tags
    - multiple affixed placeholders exist in the text
    - no affixed placeholder exists
    """
    if _TAG_RE.search(text):
        return None

    matches = list(_AFFIX_AFTER_PH.finditer(text))
    if len(matches) != 1:
        return None

    match = matches[0]
    ph_name = match.group(1)
    span_start, span_end = match.span()

    # Find the sentence or line boundaries surrounding this placeholder
    # Break points: \n, or punctuation like . ! ? ;
    before = text[:span_start]
    after = text[span_end:]

    # Check clause within the line
    line_start = before.rfind("\n")
    prefix_line = before[:line_start + 1] if line_start != -1 else ""
    clause_before = before[line_start + 1:]

    # Check for period or exclamation mark in 'after'
    punct_match = re.search(r"[.!?…;]", after)
    if punct_match:
        clause_after = after[:punct_match.start()]
        punct_and_rest = after[punct_match.start():]
    else:
        clause_after = after
        punct_and_rest = ""

    clause_text = (clause_before + " " + clause_after).strip()
    clause_text = re.sub(r"\s+", " ", clause_text).strip()

    if not clause_text:
        return None

    # Only capitalize if at start of string or after sentence-ending punctuation
    if not before.strip() or re.search(r"[.!?…]\s*$", before):
        rephrased_clause = clause_text[0].upper() + clause_text[1:] + f": {{{ph_name}}}"
    else:
        rephrased_clause = clause_text + f": {{{ph_name}}}"

    return f"{prefix_line}{rephrased_clause}{punct_and_rest}"


def check_suffix_harmony(ctx: Any) -> list[Finding]:
    """Detects case/number suffixes directly attached to placeholders."""
    findings: list[Finding] = []
    order = getattr(ctx, "order", list(ctx.ru.keys()))

    for key in order:
        if key not in ctx.ru or key not in ctx.kk:
            continue
        ru_val = ctx.ru[key]
        kk_val = ctx.kk[key]
        if not kk_val:
            continue

        for m in _AFFIX_AFTER_PH.finditer(kk_val):
            ph_name = m.group(1)
            raw_suffix = m.group(2)
            suffix_clean = m.group(3).lower()

            # Ordinal suffixes like -орын are not inflectional case affixes
            if suffix_clean == "орын":
                continue

            family = kk_lang.AFFIX_FAMILY.get(suffix_clean, "case")
            # Mention variant forms (-ға/-ге/-қа/-ке) in evidence
            evidence = (
                f"Аффикс {raw_suffix} прикреплен к плейсхолдеру {{{ph_name}}}. "
                f"В казахском аффикс зависит от значения ({raw_suffix}, -ге, -ке, -ға, -қа)"
            )
            suggestion = rephrase_without_affix(kk_val)

            findings.append(
                Finding(
                    key=key,
                    issue_type="suffix_harmony",
                    severity="high",
                    source=ru_val,
                    target=kk_val,
                    evidence=evidence,
                    suggestion=suggestion,
                    confidence=0.9,
                )
            )

    return findings


def check_orthography(ctx: Any) -> list[Finding]:
    """
    Detects spelling mistakes in Kazakh:
    1. Latin homoglyphs mixed into Cyrillic words (e.g. Latin 'i' in 'Бөлімiне').
    2. Russian look-alike letter typos (e.g. 'к' instead of 'қ' when 'қайта' is frequent).
    """
    findings: list[Finding] = []
    order = getattr(ctx, "order", list(ctx.ru.keys()))

    # Build corpus word frequency over the whole kk file
    word_freq: Counter[str] = Counter()
    for key in order:
        kk_val = ctx.kk.get(key, "")
        if kk_val:
            for w in kk_lang.words(kk_val):
                word_freq[w] += 1

    for key in order:
        if key not in ctx.ru or key not in ctx.kk:
            continue
        ru_val = ctx.ru[key]
        kk_val = ctx.kk[key]
        if not kk_val or kk_val.strip() == ru_val.strip():
            continue

        ru_words_lower = set(kk_lang.words(ru_val))

        # 1. Mixed script check (Latin homoglyphs inside Cyrillic words)
        has_mixed = False
        fixed_kk = kk_val
        for m in kk_lang.WORD_RE.finditer(kk_val):
            w = m.group()
            if kk_lang.is_mixed_script(w):
                # Replace Latin homoglyphs
                w_fixed = "".join(kk_lang.LATIN_TO_CYRILLIC.get(c, c) for c in w)
                if w_fixed != w:
                    fixed_kk = fixed_kk[:m.start()] + w_fixed + fixed_kk[m.end():]
                    has_mixed = True

        if has_mixed:
            findings.append(
                Finding(
                    key=key,
                    issue_type="orthography",
                    severity="medium",
                    source=ru_val,
                    target=kk_val,
                    evidence="Смешанные латинские буквы в казахском тексте",
                    suggestion=fixed_kk,
                    confidence=0.95,
                )
            )
            continue

        # 2. Russian look-alike letter typos
        # Word seen <= 2 times that becomes a word seen >= 3 times (and >= 3x more often)
        typo_found = False
        for m in kk_lang.WORD_RE.finditer(kk_val):
            w = m.group()
            w_low = w.lower()

            # Skip Russian loanwords that are present in ru source
            if w_low in ru_words_lower:
                continue

            current_count = word_freq[w_low]
            if current_count > 2:
                continue

            # Try letter swaps from LETTER_PAIRS
            best_cand = None
            best_cand_count = 0

            for ru_char, kk_chars in kk_lang.LETTER_PAIRS.items():
                if ru_char in w_low:
                    for kk_char in kk_chars:
                        cand_low = w_low.replace(ru_char, kk_char)
                        c_count = word_freq[cand_low]
                        if c_count >= 3 and c_count >= current_count * 3:
                            if c_count > best_cand_count:
                                best_cand = cand_low
                                best_cand_count = c_count

            if best_cand:
                # Reconstruct capitalized version of best_cand
                if w.isupper():
                    cand_fixed = best_cand.upper()
                elif w[0].isupper():
                    cand_fixed = best_cand.capitalize()
                else:
                    cand_fixed = best_cand

                suggestion = kk_val[:m.start()] + cand_fixed + kk_val[m.end():]
                evidence = (
                    f"Возможная опечатка: слово '{w_low}' встречается {current_count} раз, "
                    f"а '{best_cand}' — {best_cand_count} раз"
                )
                findings.append(
                    Finding(
                        key=key,
                        issue_type="orthography",
                        severity="medium",
                        source=ru_val,
                        target=kk_val,
                        evidence=evidence,
                        suggestion=suggestion,
                        confidence=0.85,
                    )
                )
                typo_found = True
                break

    return findings


def _gather_glossary_stats(ctx: Any) -> tuple[dict[str, Counter[str]], dict[str, int]]:
    """Counts Kazakh stem frequencies for each glossary term across the dataset."""
    order = getattr(ctx, "order", list(ctx.ru.keys()))
    term_kk_counts: dict[str, Counter[str]] = {}
    term_ru_counts: dict[str, int] = {}

    for entry in ctx.glossary:
        ru_term = entry["ru"]
        counts: Counter[str] = Counter()
        ru_n = 0

        for key in order:
            ru_val = ctx.ru.get(key, "")
            kk_val = ctx.kk.get(key, "")
            if not kk_val or kk_val.strip() == ru_val.strip():
                continue

            if gl.ru_has_term(ru_val, ru_term):
                ru_n += 1
                for w in kk_lang.words(kk_val):
                    counts[w] += 1

        term_kk_counts[ru_term] = counts
        term_ru_counts[ru_term] = ru_n

    return term_kk_counts, term_ru_counts


def check_glossary_terms(ctx: Any) -> list[Finding]:
    """Checks glossary violations (strict terms) and inconsistent terms (non-strict)."""
    findings: list[Finding] = []
    if not getattr(ctx, "glossary", None):
        return findings

    order = getattr(ctx, "order", list(ctx.ru.keys()))

    # Calculate stem occurrences for each glossary term to find established variants
    # term -> dict of form -> list of keys
    term_variants_by_key: dict[str, dict[str, set[str]]] = {}
    for entry in ctx.glossary:
        ru_term = entry["ru"]
        term_variants_by_key[ru_term] = {}

    for key in order:
        ru_val = ctx.ru.get(key, "")
        kk_val = ctx.kk.get(key, "")
        if not kk_val or kk_val.strip() == ru_val.strip():
            continue

        for entry in ctx.glossary:
            ru_term = entry["ru"]
            if gl.ru_has_term(ru_val, ru_term):
                kk_base = entry["kk"].lower()
                # Find which form appears in kk
                matched_forms = set()
                for w in kk_lang.words(kk_val):
                    stem, _ = kk_lang.split_affixes(w)
                    if kk_lang.word_has_stem(w, kk_base):
                        matched_forms.add(kk_base)
                    else:
                        for var in entry.get("allowed_variants", []):
                            if kk_lang.word_has_stem(w, var.lower()):
                                matched_forms.add(var.lower())

                if not matched_forms:
                    # Check if Russian word was left in kk
                    ru_stem = gl.ru_stem(ru_term)
                    for w in kk_lang.words(kk_val):
                        if w.startswith(ru_stem):
                            matched_forms.add(f"__ru__{w}")

                    # Check rival words
                    if not matched_forms:
                        for w in kk_lang.words(kk_val):
                            stem, _ = kk_lang.split_affixes(w)
                            if len(stem) >= 3:
                                matched_forms.add(stem)

                for f_name in matched_forms:
                    term_variants_by_key[ru_term].setdefault(f_name, set()).add(key)

    for key in order:
        ru_val = ctx.ru.get(key, "")
        kk_val = ctx.kk.get(key, "")
        if not kk_val or kk_val.strip() == ru_val.strip():
            continue

        for entry in ctx.glossary:
            ru_term = entry["ru"]
            kk_term = entry["kk"]
            is_strict = bool(entry.get("strict"))

            if not gl.ru_has_term(ru_val, ru_term):
                continue

            # Does kk have the glossary term or any allowed variant?
            if gl.kk_has_any(kk_val, entry):
                continue

            # Check if Russian word was left untranslated in kk
            ru_stem_str = gl.ru_stem(ru_term)
            leftover_match = None
            for m in kk_lang.WORD_RE.finditer(kk_val):
                w = m.group()
                if gl.ru_word_matches(w, ru_term) or w.lower().startswith(ru_stem_str):
                    leftover_match = (m.start(), m.end(), w)
                    break

            if leftover_match:
                start, end, bad_word = leftover_match
                # Reconstruct replacement
                if bad_word.isupper():
                    repl = kk_term.upper()
                elif bad_word[0].isupper():
                    repl = kk_term.capitalize()
                else:
                    repl = kk_term.lower()

                suggestion = kk_val[:start] + repl + kk_val[end:]
                issue_type = "glossary_violation" if is_strict else "inconsistent_term"

                findings.append(
                    Finding(
                        key=key,
                        issue_type=issue_type,
                        severity="medium",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Оставлено русское слово '{bad_word}' вместо термина '{kk_term}'",
                        suggestion=suggestion,
                        confidence=0.9,
                    )
                )
                continue

            # Strict term violation (not Russian word, but completely wrong translation)
            if is_strict:
                findings.append(
                    Finding(
                        key=key,
                        issue_type="glossary_violation",
                        severity="medium",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Нарушен строгий глоссарный термин '{ru_term}' -> '{kk_term}'",
                        suggestion=None,
                        confidence=0.85,
                    )
                )
                continue

            # Non-strict term: check for rival translation
            # An established alternative occurs in >= 3 strings; don't report it!
            # Find the rival word in kk
            found_rival = False
            for m in kk_lang.WORD_RE.finditer(kk_val):
                w = m.group()
                stem, affixes = kk_lang.split_affixes(w)
                keys_with_stem = term_variants_by_key[ru_term].get(stem, set())
                # If used in >= 3 strings, it is an established alternative
                if len(keys_with_stem) >= 3:
                    continue

                # Check if this rival word co-occurs with this ru term
                if len(keys_with_stem) >= 1:
                    # Inflect canonical term with rival's affixes
                    fixed_word = kk_lang.inflect(kk_term, affixes)
                    if w.isupper():
                        fixed_word = fixed_word.upper()
                    elif w[0].isupper():
                        fixed_word = fixed_word.capitalize()

                    suggestion = kk_val[:m.start()] + fixed_word + kk_val[m.end():]
                    findings.append(
                        Finding(
                            key=key,
                            issue_type="inconsistent_term",
                            severity="medium",
                            source=ru_val,
                            target=kk_val,
                            evidence=f"Несогласованный перевод термина '{ru_term}' (основной вариант: '{kk_term}')",
                            suggestion=suggestion,
                            confidence=0.8,
                        )
                    )
                    found_rival = True
                    break

    return findings


def glossary_audit(ctx: Any) -> list[dict[str, Any]]:
    """Returns established alternative translations for linguist review."""
    audit_items: list[dict[str, Any]] = []
    if not getattr(ctx, "glossary", None):
        return audit_items

    order = getattr(ctx, "order", list(ctx.ru.keys()))

    for entry in ctx.glossary:
        ru_term = entry["ru"]
        kk_term = entry["kk"]
        if entry.get("strict"):
            continue

        # Find rival stems that appear in >= 3 strings
        stem_to_keys: dict[str, list[str]] = {}
        for key in order:
            ru_val = ctx.ru.get(key, "")
            kk_val = ctx.kk.get(key, "")
            if not kk_val or kk_val.strip() == ru_val.strip():
                continue

            if gl.ru_has_term(ru_val, ru_term) and not gl.kk_has_any(kk_val, entry):
                for w in kk_lang.words(kk_val):
                    stem, _ = kk_lang.split_affixes(w)
                    if len(stem) >= 3:
                        stem_to_keys.setdefault(stem, []).append(key)

        for stem, keys in stem_to_keys.items():
            if len(keys) >= 3:
                for k in keys:
                    audit_items.append({"key": k, "term": ru_term, "rival": stem, "canonical": kk_term})

    return audit_items


def check(ctx: Any) -> list[Finding]:
    """Runs all Kazakh-specific checks."""
    return check_suffix_harmony(ctx) + check_orthography(ctx) + check_glossary_terms(ctx)
