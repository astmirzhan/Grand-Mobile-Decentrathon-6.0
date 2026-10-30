"""Recall by mutation testing.

Takes the real ARB files, picks strings the tool considers clean, injects known errors of
each type into them and checks how many the tool finds with the right issue_type.

    python scripts/mutate_kk.py --source intl_ru.arb --target intl_kk.arb \
        --glossary glossary.csv [--uz intl_uz.arb] [--per-type 10] [--seed 7] [--out recall.json]

Mutations for basic types (untranslated, placeholder_mismatch, wrong_language, same_as_source)
are evaluated only when locqa.checks.basic is importable.
"""
import argparse
import json
import random
import re
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
# Wrong but plausible translations of strict glossary terms.
GLOSSARY_SWAPS = {"отбасы": "жанұя", "фракция": "топ", "бизнес": "кәсіп", "ескерту": "сақтандыру"}
# Synonyms that break consistency of a dominant translation.
INCONSISTENT_SWAPS = {"ойыншы": "ойнаушы", "тапсырма": "міндет", "дүкен": "магазин",
                      "деңгей": "дәреже", "жарыс": "бәйге", "кейіпкер": "персонаж"}
UZBEK_SAMPLES = ["Sovg'ani oling", "Yangi o'yinchilar", "Do'konga o'tish", "Mukofotni qo'lga kiriting"]


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


def run(ctx):
    out = []
    for det in detectors():
        out.extend(det(ctx))
    return out


def _word_spans(text):
    return [(m.start(), m.end(), m.group()) for m in kk_lang.WORD_RE.finditer(text)]


def mutate_orthography(text, rng, ctx):
    freq = ctx["freq"]
    words = [(s, e, w) for s, e, w in _word_spans(text)
             if freq[w.lower()] >= 5 and any(ch in TO_RUSSIAN for ch in w.lower())]
    if not words:
        return None
    s, e, w = rng.choice(words)
    idx = [i for i, ch in enumerate(w.lower()) if ch in TO_RUSSIAN]
    i = rng.choice(idx)
    repl = TO_RUSSIAN[w[i].lower()]
    new = w[:i] + (repl.upper() if w[i].isupper() else repl) + w[i + 1:]
    return text[:s] + new + text[e:]


def mutate_suffix(text, rng, _):
    m = re.search(r"\{\w+\}(?=\s)", text)
    if not m:
        return None
    return text[:m.end()] + rng.choice(["-ға", "-ге", "-дан", "-ның"]) + text[m.end():]


MAX_PER_TERM = 2  # spread mutations over terms, as a real seeded set would be


def _swap(text, table, ctx):
    """Replace a glossary term with a wrong form, only where ru really has that term."""
    used = ctx["used_terms"]
    for good, bad in table.items():
        entry = next((g for g in ctx["glossary"] if g["kk"] == good), None)
        if (entry is None or used[good] >= MAX_PER_TERM
                or not gl.ru_has_term(ctx["ru"], entry["ru"])):
            continue
        for s, e, w in _word_spans(text):
            if kk_lang.word_has_stem(w, good):
                _, affixes = kk_lang.split_affixes(w)
                new = kk_lang.inflect(bad, affixes)
                new = new.upper() if w.isupper() else (new.capitalize() if w[0].isupper() else new)
                used[good] += 1
                return text[:s] + new + text[e:]
    return None


def mutate_glossary(text, rng, ctx):
    return _swap(text, GLOSSARY_SWAPS, ctx)


def mutate_inconsistent(text, rng, ctx):
    return _swap(text, INCONSISTENT_SWAPS, ctx)


def mutate_placeholder(text, rng, _):
    m = re.search(r"\{(\w+)\}", text)
    return text[:m.start(1)] + m.group(1) + "s" + text[m.end(1):] if m else None


def mutate_untranslated(text, rng, _):
    return ""


def mutate_wrong_language(text, rng, _):
    return rng.choice(UZBEK_SAMPLES)


KAZAKH_MUTATORS = {
    "orthography": mutate_orthography,
    "suffix_harmony": mutate_suffix,
    "glossary_violation": mutate_glossary,
    "inconsistent_term": mutate_inconsistent,
}
BASIC_MUTATORS = {
    "placeholder_mismatch": mutate_placeholder,
    "untranslated": mutate_untranslated,
    "wrong_language": mutate_wrong_language,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--uz")
    ap.add_argument("--per-type", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    ru, kk = load_arb(args.source), load_arb(args.target)
    glossary = gl.load_glossary(args.glossary)
    uz = load_arb(args.uz) if args.uz else {}
    base = SimpleNamespace(ru=ru, kk=kk, en={}, uz=uz, glossary=glossary, order=list(ru),
                           descriptions={}, sections={})
    flagged = {f.key for f in run(base)}
    clean = [k for k in ru if k in kk and k not in flagged and kk[k].strip() and kk[k] != ru[k]]
    freq = Counter(w.lower() for v in kk.values() for w in kk_lang.WORD_RE.findall(v))

    mutators = dict(KAZAKH_MUTATORS)
    if len(detectors()) > 1:
        mutators.update(BASIC_MUTATORS)

    # One mutation per key, all injected into one copy of the file (like the seeded set).
    injected, used, used_terms = {}, set(), Counter()
    mutated = dict(kk)
    for issue_type, fn in mutators.items():
        pool = [k for k in clean if k not in used]
        rng.shuffle(pool)
        n = 0
        for key in pool:
            new = fn(kk[key], rng, {"freq": freq, "ru": ru[key], "glossary": glossary,
                         "used_terms": used_terms})
            if new is None or new == kk[key]:
                continue
            mutated[key] = new
            injected[key] = issue_type
            used.add(key)
            n += 1
            if n == args.per_type:
                break

    ctx = SimpleNamespace(**{**vars(base), "kk": mutated})
    found = defaultdict(set)
    for f in run(ctx):
        found[f.key].add(f.issue_type)

    per_type = defaultdict(lambda: {"injected": 0, "found_typed": 0, "found_any": 0})
    misses = []
    for key, issue_type in injected.items():
        row = per_type[issue_type]
        row["injected"] += 1
        if issue_type in found[key]:
            row["found_typed"] += 1
        if found[key]:
            row["found_any"] += 1
        if issue_type not in found[key]:
            misses.append({"key": key, "type": issue_type, "before": kk[key], "after": mutated[key],
                           "found_as": sorted(found[key])})

    total = sum(r["injected"] for r in per_type.values())
    typed = sum(r["found_typed"] for r in per_type.values())
    print(f"{'type':28} injected  recall(typed)  recall(any)")
    for t, r in sorted(per_type.items()):
        print(f"{t:28} {r['injected']:8}  {r['found_typed'] / r['injected']:13.0%}"
              f"  {r['found_any'] / r['injected']:11.0%}")
    print(f"{'TOTAL':28} {total:8}  {typed / max(total, 1):13.0%}")
    if args.out:
        Path(args.out).write_text(json.dumps({"per_type": per_type, "misses": misses},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    return per_type, misses


if __name__ == "__main__":
    main()
