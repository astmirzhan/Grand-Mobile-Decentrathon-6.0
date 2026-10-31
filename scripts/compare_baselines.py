"""Compare locqa with simpler alternatives on exactly the same data.

    python scripts/compare_baselines.py --source intl_ru.arb --target intl_kk.arb \
        --glossary glossary.csv [--en intl_en.arb] [--uz intl_uz.arb] \
        [--clean-source material_ru.arb --clean-target material_kk.arb ...] \
        [--seeds 7,11,23] [--per-variant 8] [--out compare.json]

Tools compared (built from the check modules that are installed):

* structural linter  - what ready-made Flutter ARB linters cover: missing strings,
                       placeholders, plurals (basic checks filtered to those types);
* basic rules        - all language-agnostic basic checks;
* locqa, no LLM      - basic + Kazakh + signal checks (deterministic, free).

Metrics:

* recall   - the same injected errors (scripts/mutate_kk.py) for every tool, typed;
* coverage - how many of the 11 issue types a tool can report at all;
* findings - findings on the real file after one-per-key resolution;
* clean    - findings on clean third-party ARB files (no seeded errors): each is a
             probable false alarm.

LLM checks need an API key or a cache and are not part of this offline comparison.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locqa import glossary as gl  # noqa: E402
from scripts import mutate_kk  # noqa: E402

ALL_TYPES = 11
STRUCTURAL_TYPES = {"untranslated", "placeholder_mismatch", "plural_mismatch"}


def _module_check(name):
    try:
        module = __import__(f"locqa.checks.{name}", fromlist=["check"])
    except ImportError:
        return None
    return getattr(module, "check", None)


def _only(check, types):
    def filtered(ctx):
        return [f for f in check(ctx) if f.issue_type in types]
    return filtered


def tools():
    basic, kazakh, signals = (_module_check(n) for n in ("basic", "kazakh", "signals"))
    out = {}
    if basic:
        out["structural linter"] = ([_only(basic, STRUCTURAL_TYPES)], STRUCTURAL_TYPES)
        out["basic rules"] = ([basic], None)
    full = [c for c in (basic, kazakh, signals) if c]
    out["locqa, no LLM"] = (full, None)
    return out


def _resolve(findings, order):
    try:
        from locqa.resolve import resolve_findings  # noqa: PLC0415
    except ImportError:
        return findings
    return resolve_findings(findings, order)


def load_pairs(sources, targets):
    ru, kk = {}, {}
    for i, (s, t) in enumerate(zip(sources, targets)):
        ru.update({f"{i}.{k}": v for k, v in mutate_kk.load_arb(s).items()})
        kk.update({f"{i}.{k}": v for k, v in mutate_kk.load_arb(t).items()})
    return ru, kk


def evaluate(args):
    ru, kk = mutate_kk.load_arb(args.source), mutate_kk.load_arb(args.target)
    en = mutate_kk.load_arb(args.en) if args.en else {}
    uz = mutate_kk.load_arb(args.uz) if args.uz else {}
    glossary = gl.load_glossary(args.glossary)
    seeds = [int(s) for s in args.seeds.split(",")]
    available = tools()
    reference = available["locqa, no LLM"][0]

    clean_ru, clean_kk = (load_pairs(args.clean_source, args.clean_target)
                          if args.clean_source else ({}, {}))

    results = {}
    for name, (dets, types) in available.items():
        recalls, typed_hits = [], set()
        for seed in seeds:
            rows, _ = mutate_kk.run_once(ru, kk, uz, glossary, args.per_variant, seed,
                                         dets=dets, all_variants=True, clean_dets=reference, en=en)
            found = sum(r["found_typed"] for r in rows.values())
            total = sum(r["injected"] for r in rows.values())
            recalls.append(found / total if total else 0.0)
            typed_hits |= {r["type"] for r in rows.values() if r["found_typed"]}

        real_ctx = SimpleNamespace(ru=ru, kk=kk, en=en, uz=uz, glossary=glossary, order=list(ru),
                                   descriptions={}, sections={})
        real = _resolve(mutate_kk.run(real_ctx, dets), list(ru))
        clean = []
        if clean_ru:
            clean_ctx = SimpleNamespace(ru=clean_ru, kk=clean_kk, en={}, uz={}, glossary=glossary,
                                        order=list(clean_ru), descriptions={}, sections={})
            clean = _resolve(mutate_kk.run(clean_ctx, dets), list(clean_ru))

        reportable = len(types) if types else ALL_TYPES
        results[name] = {
            "recall_mean": statistics.mean(recalls),
            "recall_min": min(recalls),
            "recall_max": max(recalls),
            "types_reportable": reportable,
            "types_found_in_test": len(typed_hits),
            "findings_real_file": len(real),
            "clean_strings": len(clean_kk),
            "clean_findings": len(clean),
            "clean_examples": [f"{f.key}: {f.issue_type}" for f in clean[:5]],
        }
    return results


def print_table(results):
    print("| Tool | Recall, typed (mean, range) | Issue types | Findings on real file "
          "| Findings on clean file |")
    print("|---|---|---|---|---|")
    for name, r in results.items():
        clean = (f"{r['clean_findings']} of {r['clean_strings']} strings"
                 if r["clean_strings"] else "n/a")
        print(f"| {name} | {r['recall_mean']:.0%} ({r['recall_min']:.0%}–{r['recall_max']:.0%}) "
              f"| {r['types_reportable']} of {ALL_TYPES} | {r['findings_real_file']} | {clean} |")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--en")
    ap.add_argument("--uz")
    ap.add_argument("--clean-source", nargs="*", default=[])
    ap.add_argument("--clean-target", nargs="*", default=[])
    ap.add_argument("--seeds", default="7,11,23")
    ap.add_argument("--per-variant", type=int, default=8)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    if len(args.clean_source) != len(args.clean_target):
        ap.error("--clean-source and --clean-target need the same number of files")
    results = evaluate(args)
    print_table(results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    main()
