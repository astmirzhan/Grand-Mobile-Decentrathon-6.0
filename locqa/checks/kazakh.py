"""Kazakh language QA checks: orthography, suffix harmony, glossary consistency."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
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

STOP_WORDS = {
    "сіз", "біз", "олар", "мен", "пен", "бен", "үшін", "және", "де", "да", "та", "те",
    "егер", "кейбір", "барлық", "болады", "болу", "болуы", "керек", "арқылы", "туралы",
    "бойынша", "дейін", "бастап", "тек", "осы", "бұл", "сол", "бір", "екі", "үш", "төрт",
    "бес", "алты", "жеті", "сегіз", "тоғыз", "он", "жаңа", "жақсы", "үлкен", "кіші",
    "қайта", "қалай", "не", "қайда", "қашан", "кім", "жоқ", "бар", "алу", "беру", "қою",
    "ету", "істеу", "өту", "келу", "кету", "шығу", "кіру", "ашу", "жабу", "басу", "салу",
    "келе", "ме", "ма", "бе", "ба", "пе", "па", "шынымен", "немесе", "бірге", "қажет",
    "болып", "болса", "болған", "деген", "етіп", "еткен", "етіңіз", "алыңыз", "беріңіз",
    "сондықтан", "мүмкін", "арналған", "болатын", "қазір", "енді", "кейін",
}

KNOWN_RIVALS: dict[str, set[str]] = {
    "игрок": {"ойнаушы"},
    "ойыншы": {"ойнаушы"},
    "задание": {"міндет"},
    "тапсырма": {"міндет"},
    "магазин": {"дүкен"},
    "дүкен": {"магазин"},
    "уровень": {"дәреже"},
    "деңгей": {"дәреже"},
    "гонка": {"бәйге"},
    "жарыс": {"бәйге"},
    "персонаж": {"персонаж", "кейіпкер"},
    "кейіпкер": {"персонаж"},
    "пополнение": {"қайтару"},
    "толтыру": {"қайтару"},
    "заказ": {"тапсырма"},
    "тапсырыс": {"тапсырма"},
    "скидка": {"ысырама"},
    "жеңілдік": {"ысырама"},
    "символ": {"символ"},
    "таңба": {"символ"},
    "крафт": {"қолөнер"},
    "отбасы": {"жанұя"},
    "семья": {"жанұя"},
    "фракция": {"топ"},
    "бизнес": {"кәсіп"},
    "ескерту": {"сақтандыру"},
}


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

    before = text[:span_start]
    after = text[span_end:]

    line_start = before.rfind("\n")
    prefix_line = before[:line_start + 1] if line_start != -1 else ""
    clause_before = before[line_start + 1:]

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

            if suffix_clean == "орын":
                continue

            family = kk_lang.AFFIX_FAMILY.get(suffix_clean, "case")
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
        typo_found = False
        for m in kk_lang.WORD_RE.finditer(kk_val):
            w = m.group()
            w_low = w.lower()

            # Skip single-character or 2-character words (abbreviations like "к." for күн, valid words like "оз")
            if len(w_low) < 3:
                continue

            # Skip Russian loanwords that are present in ru source
            if w_low in ru_words_lower:
                continue

            current_count = word_freq[w_low]
            if current_count > 2:
                continue

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


def check_glossary_terms(ctx: Any) -> list[Finding]:
    """Checks glossary violations (strict terms) and inconsistent terms (non-strict)."""
    findings: list[Finding] = []
    if not getattr(ctx, "glossary", None):
        return findings

    order = getattr(ctx, "order", list(ctx.ru.keys()))

    stem_to_keys: dict[str, set[str]] = defaultdict(set)
    for k in order:
        kk_val = ctx.kk.get(k, "")
        if not kk_val:
            continue
        for w in kk_lang.words(kk_val):
            st, _ = kk_lang.split_affixes(w)
            if len(st) >= 3:
                stem_to_keys[st].add(k)

    term_to_keys: dict[str, set[str]] = {}
    for entry in ctx.glossary:
        ru_term = entry["ru"]
        matched = set()
        for k in order:
            r_val = ctx.ru.get(k, "")
            if r_val and gl.ru_has_term(r_val, ru_term):
                matched.add(k)
        term_to_keys[ru_term] = matched

    for entry in ctx.glossary:
        ru_term = entry["ru"]
        kk_term = entry["kk"]
        is_strict = bool(entry.get("strict"))

        matching_keys = [
            k for k in order
            if k in ctx.ru and k in ctx.kk
            and ctx.kk[k] and ctx.kk[k].strip() != ctx.ru[k].strip()
            and k in term_to_keys[ru_term]
        ]
        if not matching_keys:
            continue

        canonical_keys = [k for k in matching_keys if gl.kk_has_any(ctx.kk[k], entry)]
        missing_keys = [k for k in matching_keys if k not in canonical_keys]
        if not missing_keys:
            continue

        # 1. Strict glossary terms
        if is_strict:
            for k in missing_keys:
                kk_val = ctx.kk[k]
                ru_val = ctx.ru[k]
                ru_stem_str = gl.ru_stem(ru_term)
                leftover = None
                for m in kk_lang.WORD_RE.finditer(kk_val):
                    w = m.group()
                    if gl.ru_word_matches(w, ru_term) or (w.lower().startswith(ru_stem_str) and len(ru_stem_str) >= 4):
                        leftover = (m.start(), m.end(), w)
                        break
                if leftover:
                    s, e, bad_w = leftover
                    if bad_w.isupper():
                        repl = kk_term.upper()
                    elif bad_w[0].isupper():
                        repl = kk_term.capitalize()
                    else:
                        repl = kk_term.lower()
                    sugg = kk_val[:s] + repl + kk_val[e:]
                    findings.append(
                        Finding(
                            key=k,
                            issue_type="glossary_violation",
                            severity="medium",
                            source=ru_val,
                            target=kk_val,
                            evidence=f"Оставлено русское слово '{bad_w}' вместо термина '{kk_term}'",
                            suggestion=sugg,
                            confidence=0.9,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            key=k,
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

        # 2. Non-strict terms require dominant translation (ratio >= 0.80 and total >= 5)
        total_matching = len(matching_keys)
        ratio = len(canonical_keys) / total_matching
        if ratio < 0.80 or total_matching < 5:
            continue

        stem_counts: Counter[str] = Counter()
        for k in missing_keys:
            seen_in_key = set()
            for w in kk_lang.words(ctx.kk[k]):
                st, _ = kk_lang.split_affixes(w)
                if len(st) >= 3 and st not in seen_in_key:
                    seen_in_key.add(st)
                    stem_counts[st] += 1

        known_rivals = KNOWN_RIVALS.get(ru_term, set()) | KNOWN_RIVALS.get(kk_term, set())

        for k in missing_keys:
            kk_val = ctx.kk[k]
            ru_val = ctx.ru[k]

            # A. Check if Russian word was left untranslated
            ru_stem_str = gl.ru_stem(ru_term)
            leftover = None
            for m in kk_lang.WORD_RE.finditer(kk_val):
                w = m.group()
                if gl.ru_word_matches(w, ru_term) or (w.lower().startswith(ru_stem_str) and len(ru_stem_str) >= 4):
                    leftover = (m.start(), m.end(), w)
                    break
            if leftover:
                s, e, bad_w = leftover
                if bad_w.isupper():
                    repl = kk_term.upper()
                elif bad_w[0].isupper():
                    repl = kk_term.capitalize()
                else:
                    repl = kk_term.lower()
                sugg = kk_val[:s] + repl + kk_val[e:]
                findings.append(
                    Finding(
                        key=k,
                        issue_type="inconsistent_term",
                        severity="medium",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Оставлено русское слово '{bad_w}' вместо термина '{kk_term}'",
                        suggestion=sugg,
                        confidence=0.9,
                    )
                )
                continue

            # B. Established alternative: occurs in >= 3 strings and >= 10% of total
            is_established = False
            for w in kk_lang.words(kk_val):
                st, _ = kk_lang.split_affixes(w)
                if len(st) >= 3 and stem_counts[st] >= 3 and (stem_counts[st] / total_matching) >= 0.10:
                    is_established = True
                    break
            if is_established:
                continue

            # C. Check rival word
            found_rival = None
            for m in kk_lang.WORD_RE.finditer(kk_val):
                w = m.group()
                st, aff = kk_lang.split_affixes(w)
                if len(st) < 3 or st in STOP_WORDS:
                    continue

                if st in known_rivals or any(kk_lang.word_has_stem(w, r) for r in known_rivals):
                    found_rival = (m, st, aff, w)
                    break

            if found_rival:
                m, st, aff, w = found_rival
                fixed_w = kk_lang.inflect(kk_term, aff)
                if w.isupper():
                    fixed_w = fixed_w.upper()
                elif w[0].isupper():
                    fixed_w = fixed_w.capitalize()
                sugg = kk_val[:m.start()] + fixed_w + kk_val[m.end():]
                findings.append(
                    Finding(
                        key=k,
                        issue_type="inconsistent_term",
                        severity="medium",
                        source=ru_val,
                        target=kk_val,
                        evidence=f"Несогласованный перевод термина '{ru_term}' (основной вариант: '{kk_term}')",
                        suggestion=sugg,
                        confidence=0.8,
                    )
                )

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

        matching_keys = [
            k for k in order
            if k in ctx.ru and k in ctx.kk
            and ctx.kk[k] and ctx.kk[k].strip() != ctx.ru[k].strip()
            and gl.ru_has_term(ctx.ru[k], ru_term)
        ]
        if not matching_keys:
            continue

        canonical_keys = [k for k in matching_keys if gl.kk_has_any(ctx.kk[k], entry)]
        missing_keys = [k for k in matching_keys if k not in canonical_keys]
        if not missing_keys:
            continue

        total_matching = len(matching_keys)
        stem_to_keys: dict[str, list[str]] = {}
        for k in missing_keys:
            for w in kk_lang.words(ctx.kk[k]):
                st, _ = kk_lang.split_affixes(w)
                if len(st) >= 3 and st not in STOP_WORDS:
                    stem_to_keys.setdefault(st, []).append(k)

        for st, keys in stem_to_keys.items():
            if len(keys) >= 3 and (len(keys) / total_matching) >= 0.10:
                for k in keys:
                    audit_items.append({"key": k, "term": ru_term, "rival": st, "canonical": kk_term})

    return audit_items


def check(ctx: Any) -> list[Finding]:
    """Runs all Kazakh-specific checks."""
    return check_suffix_harmony(ctx) + check_orthography(ctx) + check_glossary_terms(ctx)
