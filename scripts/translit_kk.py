"""Transliterate a Kazakh ARB file to the Latin alphabet and report strings that grow.

    python scripts/translit_kk.py intl_kk.arb --out intl_kk_latn.arb [--report growth.csv]

The file is rewritten line by line, so @@comment markers, key order and formatting survive.
A string is reported when it grows by more than GROWTH_RATIO and at least GROWTH_MIN_CHARS
(digraphs like ш -> ş are 1:1, but ц -> ts, ч -> ch, ю -> iu, я -> ia add characters).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locqa.lang.translit import to_latin  # noqa: E402

GROWTH_RATIO = 1.1
GROWTH_MIN_CHARS = 3

_LINE = re.compile(r'^(\s*"(?P<key>[^"\\]+)"\s*:\s*)(?P<val>"(?:[^"\\]|\\.)*")(?P<tail>\s*,?\s*)$')


def transliterate_lines(lines):
    out, grown = [], []
    for line in lines:
        m = _LINE.match(line.rstrip("\n"))
        if not m or m.group("key").startswith("@"):
            out.append(line)
            continue
        value = json.loads(m.group("val"))
        latin = to_latin(value)
        if len(latin) - len(value) >= GROWTH_MIN_CHARS and len(latin) > len(value) * GROWTH_RATIO:
            grown.append({"key": m.group("key"), "cyrillic": value, "latin": latin,
                          "len_cyrillic": len(value), "len_latin": len(latin)})
        if m.group("key") == "@@locale":
            latin = value
        encoded = json.dumps(latin, ensure_ascii=False)
        out.append(f"{m.group(1)}{encoded}{m.group('tail')}" + ("\n" if line.endswith("\n") else ""))
    return out, grown


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("arb")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    args = ap.parse_args(argv)
    lines = Path(args.arb).read_text(encoding="utf-8").splitlines(keepends=True)
    out, grown = transliterate_lines(lines)
    Path(args.out).write_text("".join(out), encoding="utf-8")
    print(f"{len(grown)} strings grew by >{GROWTH_RATIO - 1:.0%} and ≥{GROWTH_MIN_CHARS} chars")
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["key", "cyrillic", "latin", "len_cyrillic", "len_latin"])
            w.writeheader()
            w.writerows(grown)
    return grown


if __name__ == "__main__":
    main()
