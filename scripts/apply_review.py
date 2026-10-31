"""Переносит разметку носителя в итоговый отчёт.

    python scripts/apply_review.py --report out/report.json \
        --reviewed review_A_done.csv review_B_done.csv review_C_done.csv --out out/final/report.json

verdict 0 убирает находку из отчёта. Подтверждённая находка получает reviewed_by_human и итоговый текст.
Ошибки смысла попадают в отчёт только подтверждёнными человеком. Строки без вердикта остаются как были.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa.models import Finding  # noqa: E402
from locqa.report import write_html_report, write_json_report  # noqa: E402
from locqa.sheet import _uncell  # noqa: E402


def load_reviewed(paths: list[str]) -> dict[tuple[str, str], dict]:
    rows = {}
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["key"], r["issue_type"])] = r
    return rows


def final_text(row: dict) -> str:
    return _uncell(row.get("итоговый_текст")) or _uncell(row.get("suggestion"))


def apply_review(report: list[dict], reviewed: dict[tuple[str, str], dict]) -> list[Finding]:
    fields = Finding.__dataclass_fields__
    out, seen = [], set()
    for item in report:
        pair = (item["key"], item["issue_type"])
        seen.add(pair)
        row = reviewed.get(pair)
        if row and row.get("verdict") == "0":
            continue
        f = Finding(**{k: v for k, v in item.items() if k in fields})
        if row and row.get("verdict") in ("1", "t"):
            f.reviewed_by_human = True
            f.suggestion = final_text(row) or f.suggestion
        out.append(f)
    for pair, row in reviewed.items():  # подтверждённые человеком находки вне отчёта: ошибки смысла
        if pair in seen or row.get("verdict") != "1":
            continue
        out.append(Finding(
            key=row["key"], issue_type=row["issue_type"], severity=row.get("severity", ""), source=_uncell(row["ru"]),
            target=_uncell(row["kk_сейчас"]), evidence=_uncell(row["evidence"]), suggestion=final_text(row),
            confidence=1.0, reviewed_by_human=True,
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--reviewed", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    if isinstance(report, dict):
        report = report["findings"]
    findings = apply_review(report, load_reviewed(a.reviewed))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_report(findings, out)
    write_html_report(findings, out.with_suffix(".html"))
    print(f"{out}: {len(findings)} находок, проверено человеком {sum(f.reviewed_by_human for f in findings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
