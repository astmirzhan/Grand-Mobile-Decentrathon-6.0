"""Kazakh-specific checks: orthography, suffix_harmony, glossary_violation, inconsistent_term.

All checks are statistical or rule-based and read only ctx.ru, ctx.kk and ctx.glossary.
The kk file itself is the reference: seeded errors are rare distortions of an otherwise
consistent translation, so a rare spelling next to a frequent near-identical one is a typo,
and a rare translation of a term next to a dominant one is an inconsistency.
"""
import itertools
import re
from collections import Counter, defaultdict

from locqa import glossary as gl
from locqa.lang import kk as kk_lang
from locqa.lang._contract import Finding

# Orthography thresholds
RARE_MAX = 2          # a word seen at most this many times is a typo candidate
COMMON_MIN = 3        # its corrected variant must be seen at least this many times
RATIO_MIN = 3         # ... and at least RATIO_MIN times more often than the candidate
MIN_WORD_LEN = 3

# Both members of these pairs are valid Kazakh words.
VALID_PAIRS = {frozenset(p) for p in [
    ("өзіне", "өзіңе"), ("өзін", "өзің"), ("тұр", "түр"), ("кен", "кең"), ("тан", "таң"),
    ("ұл", "үл"), ("сен", "сең"),
]}

# Inconsistent term thresholds
DOMINANCE_MIN = 0.8    # the canonical translation must cover ≥80% of the term's keys
RIVAL_ALIGN_MIN = 0.5  # a rival root occurs mostly in strings that translate the same term
ALT_CLUSTER_MIN = 3    # an alternative used in ≥3 strings is established, not an error
# Non-strict terms are flagged only when the file is near-unanimous about them.
NEAR_UNANIMOUS = 0.95
NEAR_UNANIMOUS_KEYS = 20

_MARKUP_RE = re.compile(r"\{[^{}]*\}|<[^<>]+>|\\[nt]")
_STOPWORDS = set("үшін және сіз сіздің бұл мен ал бар жоқ емес болады бойынша арқылы кейін дейін "
                 "барлық әр осы сол біз олар оның ол ме ма ба бе пе па".split())


def _strip_markup(text: str) -> str:
    return _MARKUP_RE.sub(" ", text or "")


def _tokens(text: str) -> list[str]:
    """Original-case word tokens without placeholders and tags."""
    return kk_lang.WORD_RE.findall(_strip_markup(text))


def _match_case(src: str, repl: str) -> str:
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _replace_word(text: str, old: str, new: str) -> str:
    return re.sub(rf"(?<![^\W\d_]){re.escape(old)}(?![^\W\d_])", new, text, count=1)


def _usable(ru: str, kk: str) -> bool:
    """Skip strings that belong to other checks: empty, copied from ru, not Cyrillic Kazakh."""
    if not kk or not kk.strip() or kk.strip() == (ru or "").strip():
        return False
    return bool(kk_lang.CYRILLIC_RE.search(_strip_markup(kk)))


def _finding(key, issue_type, severity, ru, kk, evidence, suggestion, confidence):
    return Finding(key=key, issue_type=issue_type, severity=severity, source=ru, target=kk,
                   evidence=evidence, suggestion=suggestion, confidence=confidence)


# --------------------------------------------------------------------------- orthography

def _variants(word: str, max_subs: int = 2):
    """Spellings of `word` with 1..max_subs Russian letters swapped for Kazakh ones."""
    slots = [(i, ch) for i, ch in enumerate(word) if ch in kk_lang.LETTER_PAIRS]
    for n in range(1, max_subs + 1):
        for combo in itertools.combinations(slots, n):
            for repls in itertools.product(*(kk_lang.LETTER_PAIRS[ch] for _, ch in combo)):
                chars = list(word)
                for (i, _), r in zip(combo, repls):
                    chars[i] = r
                yield "".join(chars)


def check_orthography(ctx) -> list[Finding]:
    ru, kk = ctx.ru, ctx.kk
    freq = Counter(w.lower() for v in kk.values() for w in _tokens(v))
    ru_vocab = {w.lower() for v in ru.values() for w in _tokens(v)}
    findings = []

    for key, text in kk.items():
        src = ru.get(key, "")
        if not _usable(src, text):
            continue
        fixes, notes, conf = [], [], 0.85
        for tok in dict.fromkeys(_tokens(text)):
            low = tok.lower()
            # Latin homoglyphs inside a Cyrillic word: бөлімiне, көтерілеcің
            if kk_lang.is_mixed_script(tok):
                fixed = "".join(kk_lang.LATIN_TO_CYRILLIC.get(ch, ch) for ch in tok)
                if fixed != tok and not kk_lang.LATIN_RE.search(fixed):
                    latin = sorted({ch for ch in tok if kk_lang.LATIN_RE.match(ch)})
                    fixes.append((tok, fixed))
                    notes.append(f"«{tok}»: латинские буквы {', '.join(latin)} внутри кириллического слова")
                    conf = 0.95
                continue
            if (len(low) < MIN_WORD_LEN or freq[low] > RARE_MAX or low in ru_vocab
                    or not kk_lang.CYRILLIC_RE.search(low) or kk_lang.LATIN_RE.search(low)):
                continue
            best = max(_variants(low), key=lambda v: freq[v], default=None)
            if (best and freq[best] >= COMMON_MIN and freq[best] >= RATIO_MIN * freq[low]
                    and frozenset((low, best)) not in VALID_PAIRS):
                fixes.append((tok, _match_case(tok, best)))
                notes.append(f"«{low}» встречается {freq[low]} раз(а) в kk-файле, "
                             f"«{best}» — {freq[best]} раз")
        if fixes:
            suggestion = text
            for old, new in fixes:
                suggestion = _replace_word(suggestion, old, new)
            findings.append(_finding(key, "orthography", "medium", src, text,
                                     "; ".join(notes), suggestion, conf))
    return findings


# ------------------------------------------------------------------------ suffix_harmony

_SUFFIX_RE = re.compile(
    r"\{(\w+)\}(-?)(" + "|".join(sorted(kk_lang.SUFFIXES, key=len, reverse=True)) + r")(?![^\W\d_])",
    re.IGNORECASE,
)


def check_suffix_harmony(ctx) -> list[Finding]:
    findings = []
    for key, text in ctx.kk.items():
        hits = list(_SUFFIX_RE.finditer(text or ""))
        if not hits:
            continue
        parts = []
        for m in hits:
            name, affix = m.group(1), m.group(3).lower()
            fam = kk_lang.AFFIX_FAMILY.get(affix)
            if fam:
                forms = sorted({f for pair in kk_lang._AFFIXES[fam].values() for f in pair})
                alt = "/".join(f"-{f}" for f in forms)
            else:
                alt = "другой вариант"
            parts.append(f"после {{{name}}} жёстко стоит аффикс «-{affix}», но значение подставляется "
                         f"во время игры и может требовать {alt}")
        findings.append(_finding(
            key, "suffix_harmony", "high", ctx.ru.get(key, ""), text,
            "; ".join(parts) + ". Нужно перефразировать без аффикса после плейсхолдера "
            "или склонять в коде.",
            None, 0.9))
    return findings


# --------------------------------------------- glossary_violation + inconsistent_term

_FOLD = str.maketrans("әғқңөұүһі", "агкноуухи")


def _fold(word: str) -> str:
    """Map Kazakh letters to Russian look-alikes: көлік and колик fold to the same string."""
    return word.lower().translate(_FOLD)


def _root(word: str) -> str:
    return kk_lang.split_affixes(word.lower())[0][:6]


def _term_keys(ctx, entry) -> list[str]:
    return [k for k, v in ctx.ru.items()
            if k in ctx.kk and _usable(v, ctx.kk[k]) and gl.ru_has_term(v, entry["ru"])]


def _is_typo_of(text: str, entry: dict) -> bool:
    """The term is present but misspelled (orthography owns this case)."""
    folded = [_fold(w) for w in _tokens(text)]
    for form in gl.kk_forms(entry):
        base = _fold(kk_lang.stem(kk_lang.words(form)[0])) if kk_lang.words(form) else ""
        if base and any(w.startswith(base) for w in folded):
            return True
    return False


def _aligned_roots(ctx, key, term_set, root_keys, glossary_words):
    """Roots in this key's kk text that occur mostly in strings translating the same term."""
    roots = []
    for tok in _tokens(ctx.kk[key]):
        low = tok.lower()
        if (len(low) < 4 or low in _STOPWORDS or not kk_lang.CYRILLIC_RE.search(low)
                or any(kk_lang.word_has_stem(low, g) for g in glossary_words)):
            continue
        keys = root_keys.get(_root(low), set())
        if keys and len(keys & term_set) / len(keys) >= RIVAL_ALIGN_MIN:
            roots.append((_root(low), tok))
    return roots


def _replace_rival(text: str, rival: str, canonical: str) -> str:
    _, affixes = kk_lang.split_affixes(rival)
    words_ = canonical.split()
    words_[-1] = kk_lang.inflect(words_[-1], affixes)
    return _replace_word(text, rival, _match_case(rival, " ".join(words_)))


def _replace_russian(text: str, entry: dict) -> str | None:
    """If the Russian term itself was left in kk text, swap it for the glossary term."""
    term_words = kk_lang.words(entry["ru"])
    for tok in _tokens(text):
        if len(term_words) == 1 and gl.ru_word_matches(tok.lower(), term_words[0]) \
                and not gl.kk_has_term(tok, entry["kk"]):
            return _replace_word(text, tok, _match_case(tok, entry["kk"]))
    return None


def glossary_audit(ctx) -> list[dict]:
    """Established alternative translations (used in ≥ALT_CLUSTER_MIN strings) per term.

    These are not reported as errors; the linguist decides whether to add them to
    allowed_variants or to unify the translation.
    """
    return _analyze_terms(ctx)[1]


def _analyze_terms(ctx):
    entries = getattr(ctx, "glossary", None) or []
    findings, audit = [], []
    if not entries:
        return findings, audit
    root_keys = defaultdict(set)
    for k, v in ctx.kk.items():
        for w in _tokens(v):
            root_keys[_root(w)].add(k)
    glossary_words = {w for e in entries for f in gl.kk_forms(e) for w in kk_lang.words(f)}

    flagged = set()
    # Longer (multi-word) terms first so a phrase wins over its single-word part.
    for entry in sorted(entries, key=lambda e: -len(e["ru"])):
        keys = _term_keys(ctx, entry)
        if not keys:
            continue
        term_set = set(keys)
        hits = [k for k in keys if gl.kk_has_any(ctx.kk[k], entry)]
        misses = [k for k in keys if k not in hits and k not in flagged
                  and not _is_typo_of(ctx.kk[k], entry)]
        share = len(hits) / len(keys)
        strict = entry.get("strict", "").lower() in ("1", "true", "yes")

        # How many missing strings share each aligned root: big clusters are an
        # established alternative translation, small ones a stray variant.
        aligned = {k: _aligned_roots(ctx, k, term_set, root_keys, glossary_words) for k in misses}
        cluster = Counter(r for k in misses for r in {r for r, _ in aligned[k]})

        for key in misses:
            src, text = ctx.ru[key], ctx.kk[key]
            sizes = {r: cluster[r] for r, _ in aligned[key]}
            big = [r for r, n in sizes.items() if n >= ALT_CLUSTER_MIN]
            rivals = [(r, tok) for r, tok in aligned[key] if 2 <= sizes[r] < ALT_CLUSTER_MIN]
            if big and not strict:
                audit.append({"term": entry["ru"], "kk": entry["kk"], "alternative": big[0],
                              "count": sizes[big[0]], "key": key})
                continue
            russian = _replace_russian(text, entry)
            if strict or russian:
                # Terms the studio fixed explicitly (or a Russian word left untranslated).
                allowed = ", ".join(f"«{f}»" for f in gl.kk_forms(entry))
                findings.append(_finding(
                    key, "glossary_violation", "medium", src, text,
                    f"в исходнике термин «{entry['ru']}», в переводе нет ни одного из вариантов "
                    f"глоссария: {allowed} (по глоссарию переведено {len(hits)} из {len(keys)} строк)",
                    russian, 0.85))
            elif share >= DOMINANCE_MIN and len(hits) >= 3 and (
                    rivals or (share >= NEAR_UNANIMOUS and len(keys) >= NEAR_UNANIMOUS_KEYS)):
                # The rest of the file agrees on one translation, this string does not.
                single = [tok for r, tok in aligned[key] if sizes[r] == 1]
                rival = rivals[0][1] if rivals else (single[0] if len(single) == 1 else None)
                where = f", здесь — «{rival}»" if rival else ", здесь термин переведён иначе"
                findings.append(_finding(
                    key, "inconsistent_term", "medium", src, text,
                    f"«{entry['ru']}» в {len(hits)} из {len(keys)} строк переведён как "
                    f"«{entry['kk']}»{where}",
                    _replace_rival(text, rival, entry["kk"]) if rival else None,
                    0.8 if rivals else 0.6))
            else:
                continue
            flagged.add(key)
    return findings, audit


def check_glossary_terms(ctx) -> list[Finding]:
    """glossary_violation and inconsistent_term in one pass (they share term statistics)."""
    return _analyze_terms(ctx)[0]


def check(ctx) -> list[Finding]:
    """Entry point used by the core runner."""
    return [*check_orthography(ctx), *check_suffix_harmony(ctx), *check_glossary_terms(ctx)]


CHECKS = {
    "orthography": check_orthography,
    "suffix_harmony": check_suffix_harmony,
    "glossary_terms": check_glossary_terms,
}
