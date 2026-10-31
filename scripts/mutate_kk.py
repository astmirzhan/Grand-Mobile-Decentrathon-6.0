"""Recall by mutation testing.

Takes the real ARB files, picks strings the tool considers clean, injects known errors of
each type into them and checks how many the tool finds with the right issue_type.
Mutations imitate the errors seen in the seeded file: Russian letters for Kazakh ones,
Latin homoglyphs, a Russian word left untranslated, a rival synonym, a fixed affix after a
placeholder, Uzbek text.

    python scripts/mutate_kk.py --source intl_ru.arb --target intl_kk.arb \
        --glossary glossary.csv [--uz intl_uz.arb] [--per-variant 10] \
        [--seeds 7,11,23] [--out recall.json]

Mutations for basic types (untranslated, placeholder_mismatch, wrong_language) are evaluated
only when locqa.checks.basic is importable.
"""
import argparse
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locqa import glossary as gl  # noqa: E402
from locqa.checks import kazakh  # noqa: E402
from locqa.lang import kk as kk_lang  # noqa: E402

# Kazakh letter -> Russian look-alike, the typical typo direction.
TO_RUSSIAN = {"ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и"}
# Cyrillic letter -> Latin homoglyph (бөлімiне, көтерілеcің in the seeded file).
TO_LATIN = {"і": "i", "с": "c", "о": "o", "а": "a", "е": "e", "р": "p", "х": "x"}
# Wrong but plausible translations of strict glossary terms.
GLOSSARY_SWAPS = {"отбасы": "жанұя", "фракция": "топ", "бизнес": "кәсіп", "ескерту": "сақтандыру"}
# Synonyms that break consistency of a dominant translation.
INCONSISTENT_SWAPS = {"ойыншы": "ойнаушы", "тапсырма": "міндет", "дүкен": "магазин",
                      "деңгей": "дәреже", "жарыс": "бәйге", "кейіпкер": "персонаж"}
UZBEK_SAMPLES = ["Sovg'ani oling", "Yangi o'yinchilar", "Do'konga o'tish", "Mukofotni qo'lga kiriting"]
MAX_PER_TERM = 2  # spread mutations over terms, as a real seeded set would be


def load_arb(path):
    pairs = json.load(open(path, encoding="utf-8"), object_pairs_hook=lambda p: p)
    return {k: v for k, v in pairs if not k.startswith("@") and isinstance(v, str)}


def detectors():
    found = [kazakh.check]
    try:
        from locqa.checks import basic  # noqa: PLC0415
        found.append(basic.check)
    except ImportError:
        pass
    return found


def run(ctx, dets=None):
    out = []
    for det in dets or detectors():
        out.extend(det(ctx))
    return out


def _word_spans(text):
    return [(m.start(), m.end(), m.group()) for m in kk_lang.WORD_RE.finditer(text)]


def _same_case(src, new):
    return new.upper() if src.isupper() else (new[:1].upper() + new[1:] if src[:1].isupper() else new)


def _swap_letter(text, rng, ctx, table):
    words = [(s, e, w) for s, e, w in _word_spans(text)
             if ctx["freq"][w.lower()] >= 5 and any(ch in table for ch in w.lower())]
    if not words:
        return None
    s, e, w = rng.choice(words)
    i = rng.choice([i for i, ch in enumerate(w.lower()) if ch in table])
    repl = table[w[i].lower()]
    new = w[:i] + (repl.upper() if w[i].isupper() else repl) + w[i + 1:]
    return text[:s] + new + text[e:]


def mutate_russian_letter(text, rng, ctx):
    return _swap_letter(text, rng, ctx, TO_RUSSIAN)


def mutate_latin_letter(text, rng, ctx):
    return _swap_letter(text, rng, ctx, TO_LATIN)


def mutate_suffix_hyphen(text, rng, ctx):
    m = re.search(r"\{\w+\}(?=\s)", text)
    return text[:m.end()] + rng.choice(["-ға", "-ге", "-дан", "-ның"]) + text[m.end():] if m else None


def mutate_suffix_plain(text, rng, ctx):
    m = re.search(r"\{\w+\}(?=\s)", text)
    return text[:m.end()] + rng.choice(["ға", "ге", "дан", "ның"]) + text[m.end():] if m else None


def _terms(ctx, strict):
    return [g for g in ctx["glossary"]
            if (g.get("strict", "").lower() in ("1", "true", "yes")) == strict
            and ctx["used_terms"][g["kk"]] < MAX_PER_TERM and gl.ru_has_term(ctx["ru"], g["ru"])]


def _replace_term(text, entry, ctx, new_base):
    for s, e, w in _word_spans(text):
        if kk_lang.word_has_stem(w, entry["kk"].split()[-1]):
            _, affixes = kk_lang.split_affixes(w)
            ctx["used_terms"][entry["kk"]] += 1
            return text[:s] + _same_case(w, kk_lang.inflect(new_base, affixes)) + text[e:]
    return None


def _swap(text, ctx, table, strict):
    for entry in _terms(ctx, strict):
        if entry["kk"] in table:
            new = _replace_term(text, entry, ctx, table[entry["kk"]])
            if new:
                return new
    return None


def _russian_left(text, ctx, strict):
    """Put the Russian word for a glossary term into the kk text (Предмет бұрын сатып алынған)."""
    for entry in _terms(ctx, strict):
        ru_word = next((w for w in kk_lang.words(ctx["ru"])
                        if gl.ru_word_matches(w, kk_lang.words(entry["ru"])[0])), None)
        # Skip no-op or legitimate cases: the Russian form equals the Kazakh term (баланс),
        # is an allowed variant (автомобиль), or the string is a single word (that is
        # same_as_source, not a term error).
        if (not ru_word or len(kk_lang.words(entry["ru"])) != 1 or len(kk_lang.words(text)) < 2
                or gl.kk_has_any(ru_word, entry)):
            continue
        if ru_word:
            for s, e, w in _word_spans(text):
                if kk_lang.word_has_stem(w, entry["kk"].split()[-1]):
                    ctx["used_terms"][entry["kk"]] += 1
                    return text[:s] + _same_case(w, ru_word) + text[e:]
    return None


def mutate_glossary_synonym(text, rng, ctx):
    return _swap(text, ctx, GLOSSARY_SWAPS, strict=True)


def mutate_glossary_russian(text, rng, ctx):
    return _russian_left(text, ctx, strict=True)


def mutate_inconsistent_synonym(text, rng, ctx):
    return _swap(text, ctx, INCONSISTENT_SWAPS, strict=False)


def mutate_inconsistent_russian(text, rng, ctx):
    return _russian_left(text, ctx, strict=False)


def mutate_placeholder(text, rng, ctx):
    m = re.search(r"\{(\w+)\}", text)
    return text[:m.start(1)] + m.group(1) + "s" + text[m.end(1):] if m else None


def mutate_untranslated(text, rng, ctx):
    return ""


def mutate_wrong_language(text, rng, ctx):
    return ctx["uz"] if ctx["uz"] and ctx["uz"] != ctx["ru"] else rng.choice(UZBEK_SAMPLES)


# (variant, expected issue_type, mutator)
KAZAKH_VARIANTS = [
    ("russian_letter", "orthography", mutate_russian_letter),
    ("latin_homoglyph", "orthography", mutate_latin_letter),
    ("affix_hyphen", "suffix_harmony", mutate_suffix_hyphen),
    ("affix_plain", "suffix_harmony", mutate_suffix_plain),
    ("strict_synonym", "glossary_violation", mutate_glossary_synonym),
    ("strict_russian_left", "glossary_violation", mutate_glossary_russian),
    ("rival_synonym", "inconsistent_term", mutate_inconsistent_synonym),
    ("russian_left", "inconsistent_term", mutate_inconsistent_russian),
]
BASIC_VARIANTS = [
    ("broken_placeholder", "placeholder_mismatch", mutate_placeholder),
    ("empty", "untranslated", mutate_untranslated),
    ("uzbek_text", "wrong_language", mutate_wrong_language),
]


def run_once(ru, kk, uz, glossary, per_variant, seed, dets=None, all_variants=None,
             clean_dets=None, en=None):
    """One mutation run. `dets` are the detectors under test; `clean_dets` pick the clean
    strings to mutate (default: the same detectors), so different tools can be compared on
    exactly the same injected errors."""
    rng = random.Random(seed)
    base = SimpleNamespace(ru=ru, kk=kk, en=en or {}, uz=uz, glossary=glossary, order=list(ru),
                           descriptions={}, sections={})
    flagged = {f.key for f in run(base, clean_dets or dets)}
    clean = [k for k in ru if k in kk and k not in flagged and kk[k].strip() and kk[k] != ru[k]]
    freq = Counter(w.lower() for v in kk.values() for w in kk_lang.WORD_RE.findall(v))
    if all_variants is None:
        all_variants = len(detectors()) > 1
    variants = KAZAKH_VARIANTS + (BASIC_VARIANTS if all_variants else [])

    # One mutation per key, all injected into one copy of the file (like the seeded set).
    injected, used_keys, used_terms = {}, set(), Counter()
    mutated = dict(kk)
    for name, issue_type, fn in variants:
        pool = [k for k in clean if k not in used_keys]
        rng.shuffle(pool)
        n = 0
        for key in pool:
            ctx = {"freq": freq, "ru": ru[key], "uz": uz.get(key, ""), "glossary": glossary,
                   "used_terms": used_terms}
            new = fn(kk[key], rng, ctx)
            if new is None or new == kk[key]:
                continue
            mutated[key] = new
            injected[key] = (name, issue_type)
            used_keys.add(key)
            n += 1
            if n == per_variant:
                break

    found = defaultdict(set)
    for f in run(SimpleNamespace(**{**vars(base), "kk": mutated}), dets):
        found[f.key].add(f.issue_type)

    rows = defaultdict(lambda: {"type": "", "injected": 0, "found_typed": 0, "found_any": 0})
    misses = []
    for key, (name, issue_type) in injected.items():
        row = rows[name]
        row["type"] = issue_type
        row["injected"] += 1
        row["found_typed"] += issue_type in found[key]
        row["found_any"] += bool(found[key])
        if issue_type not in found[key]:
            misses.append({"seed": seed, "key": key, "variant": name, "type": issue_type,
                           "before": kk[key], "after": mutated[key], "found_as": sorted(found[key])})
    return rows, misses


def summarize(runs):
    """Mean and range of typed recall per variant and per issue type over several seeds."""
    def rate(found, total):
        return found / total if total else None

    by_variant, by_type = defaultdict(list), defaultdict(list)
    totals = []
    for rows in runs:
        per_type = defaultdict(lambda: [0, 0])
        for name, r in rows.items():
            by_variant[(r["type"], name)].append(rate(r["found_typed"], r["injected"]))
            per_type[r["type"]][0] += r["found_typed"]
            per_type[r["type"]][1] += r["injected"]
        for t, (f, n) in per_type.items():
            by_type[t].append(rate(f, n))
        totals.append(rate(sum(f for f, _ in per_type.values()), sum(n for _, n in per_type.values())))

    def line(label, values):
        values = [v for v in values if v is not None]
        if not values:
            return f"{label:44} n/a"
        return (f"{label:44} {statistics.mean(values):6.0%}   "
                f"{min(values):4.0%}–{max(values):.0%}")

    print(f"{'type / variant':44} {'mean':>6}   range")
    for t in sorted(by_type):
        print(line(t, by_type[t]))
        for (vt, name), vals in sorted(by_variant.items()):
            if vt == t:
                print(line(f"  {name}", vals))
    print(line("TOTAL", totals))
    return {"by_type": dict(by_type), "by_variant": {f"{t}/{n}": v for (t, n), v in by_variant.items()},
            "total": totals}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--uz")
    ap.add_argument("--per-variant", "--per-type", dest="per_variant", type=int, default=10)
    ap.add_argument("--seeds", "--seed", dest="seeds", default="7",
                    help="one seed or a comma-separated list: 7,11,23")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    ru, kk = load_arb(args.source), load_arb(args.target)
    uz = load_arb(args.uz) if args.uz else {}
    glossary = gl.load_glossary(args.glossary)
    runs, misses = [], []
    for seed in (int(s) for s in args.seeds.split(",")):
        rows, m = run_once(ru, kk, uz, glossary, args.per_variant, seed)
        runs.append(rows)
        misses.extend(m)
    summary = summarize(runs)
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "misses": misses},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, misses


if __name__ == "__main__":
    main()
