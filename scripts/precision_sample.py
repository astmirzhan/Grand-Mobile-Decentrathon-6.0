"""Precision by manual labelling of a random sample of findings.

1) Draw a sample to label (from the team report, or straight from the Kazakh checks):

    python scripts/precision_sample.py sample --report report.json --n 100 --out sample.csv
    python scripts/precision_sample.py sample --source intl_ru.arb --target intl_kk.arb \
        --glossary glossary.csv --n 100 --out sample.csv

2) A native speaker fills the `verdict` column: 1 = real error of this type,
   0 = false alarm, t = real error but wrong issue_type (counted as a miss for precision).

3) Score:

    python scripts/precision_sample.py score sample.csv
"""
import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIELDS = ["id", "key", "issue_type", "severity", "confidence", "source", "target",
          "evidence", "suggestion", "verdict", "reviewer", "note"]
POSITIVE = {"1", "y", "yes", "да", "+", "✅"}
WRONG_TYPE = {"t", "type"}


def load_findings(args) -> list[dict]:
    if args.report:
        data = json.load(open(args.report, encoding="utf-8"))
        return data["findings"] if isinstance(data, dict) else data
    from locqa.checks import kazakh  # noqa: PLC0415
    from locqa.glossary import load_glossary  # noqa: PLC0415
    from scripts.mutate_kk import load_arb  # noqa: PLC0415
    ru = load_arb(args.source)
    ctx = SimpleNamespace(ru=ru, kk=load_arb(args.target), glossary=load_glossary(args.glossary),
                          order=list(ru))
    return [asdict(f) if is_dataclass(f) else vars(f) for f in kazakh.check(ctx)]


def cmd_sample(args):
    findings = load_findings(args)
    rng = random.Random(args.seed)
    sample = findings if len(findings) <= args.n else rng.sample(findings, args.n)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for i, row in enumerate(sample, 1):
            w.writerow({**row, "id": i, "verdict": "", "reviewer": "", "note": ""})
    print(f"{len(sample)} of {len(findings)} findings written to {args.out}")


def cmd_score(args):
    rows = list(csv.DictReader(open(args.sample, encoding="utf-8-sig")))
    per_type = defaultdict(lambda: [0, 0])
    unlabeled = 0
    for r in rows:
        v = (r.get("verdict") or "").strip().lower()
        if not v:
            unlabeled += 1
            continue
        per_type[r["issue_type"]][1] += 1
        if v in POSITIVE:
            per_type[r["issue_type"]][0] += 1
        elif v not in WRONG_TYPE and v not in {"0", "n", "no", "нет", "-", "❌"}:
            print(f"warning: unknown verdict {v!r} in row {r.get('id')}", file=sys.stderr)
    tp = sum(p for p, _ in per_type.values())
    total = sum(n for _, n in per_type.values())
    print(f"{'type':28} labelled  precision")
    for t, (p, n) in sorted(per_type.items()):
        print(f"{t:28} {n:8}  {p / n:9.0%}")
    print(f"{'TOTAL':28} {total:8}  {tp / max(total, 1):9.0%}")
    if unlabeled:
        print(f"({unlabeled} rows without verdict skipped)")
    return {t: p / n for t, (p, n) in per_type.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--report")
    s.add_argument("--source")
    s.add_argument("--target")
    s.add_argument("--glossary")
    s.add_argument("--n", type=int, default=100)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_sample)
    c = sub.add_parser("score")
    c.add_argument("sample")
    c.set_defaults(func=cmd_score)
    args = ap.parse_args(argv)
    if args.cmd == "sample" and not args.report and not (args.source and args.target and args.glossary):
        ap.error("sample needs --report or --source/--target/--glossary")
    return args.func(args)


if __name__ == "__main__":
    main()
