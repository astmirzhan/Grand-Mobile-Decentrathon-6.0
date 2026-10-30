"""Таблица ревью для Google Таблиц: экспорт находок и импорт решений носителей.

Экспорт: review_all.csv + review_A.csv / review_B.csv / review_C.csv (три равные части).
Импорт: читает заполненные CSV и пишет decisions.csv для fix.py — только ✅ и ✏.

    python -m locqa.sheet export --report report.json --source intl_ru.arb --target intl_kk.arb \
        --ref intl_en.arb --out-dir out/review
    python -m locqa.sheet import out/review/review_*.csv --source intl_ru.arb --out out/decisions.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .models import Context, Finding
from .suggest import placeholders

COLUMNS = [
    "id", "key", "issue_type", "severity", "ru", "en", "kk_сейчас",
    "evidence", "suggestion", "решение", "итоговый_текст", "кто_проверил",
]
DECISION_COLUMNS = ["key", "issue_type", "final_text", "reviewer", "finding_id"]
REVIEWERS = ("A", "B", "C")

ACCEPT = {"✅", "+", "ok", "да", "accept", "принять", "y"}
EDIT = {"✏", "✏️", "edit", "свой", "e"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Google Таблицы считают формулой текст, начинающийся с этих символов
_FORMULA_START = ("=", "+", "-", "@")


def _cell(text: str | None) -> str:
    text = text or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _uncell(text: str | None) -> str:
    text = text or ""
    return text[1:] if text.startswith("'") and text[1:2] in _FORMULA_START else text


def _sort_key(f: Finding):
    return (SEVERITY_ORDER.get(f.severity, 3), f.issue_type, f.key)


def export(ctx: Context, findings: list[Finding], out_dir: str | Path, reviewers=REVIEWERS) -> list[Path]:
    """Одна строка на находку. Внутри части строки сгруппированы по типу — так ревьюить быстрее."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, f in enumerate(sorted(findings, key=_sort_key), 1):
        rows.append({
            "id": f"{i:04d}",
            "key": f.key,
            "issue_type": f.issue_type,
            "severity": f.severity,
            "ru": _cell(ctx.ru.get(f.key, f.source)),
            "en": _cell(ctx.en.get(f.key, "")),
            "kk_сейчас": _cell(ctx.kk.get(f.key, f.target)),
            "evidence": _cell(f.evidence),
            "suggestion": _cell(f.suggestion),
            "решение": "",
            "итоговый_текст": "",
            "кто_проверил": reviewers[(i - 1) % len(reviewers)],  # по кругу: у каждого все типы поровну
        })
    paths = [_write(out_dir / "review_all.csv", rows, COLUMNS)]
    for r in reviewers:
        paths.append(_write(out_dir / f"review_{r}.csv", [x for x in rows if x["кто_проверил"] == r], COLUMNS))
    return paths


def _write(path: Path, rows: list[dict], columns: list[str]) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def load_decisions(paths: list[str | Path], ru: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Возвращает (решения ✅/✏, предупреждения). ❌ и пустые строки пропускаются."""
    decisions: dict[str, dict] = {}
    warnings: list[str] = []
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                mark = (row.get("решение") or "").strip().lower()
                own = _uncell(row.get("итоговый_текст")).strip()
                suggestion = _uncell(row.get("suggestion")).strip()
                where = f'{Path(path).name} id={row.get("id")} key={row.get("key")}'
                if mark in EDIT or (mark in ACCEPT and own):
                    final = own
                elif mark in ACCEPT:
                    final = suggestion
                else:
                    continue
                key = row["key"]
                if not final:
                    warnings.append(f"{where}: решение «{mark}», но текста нет — пропущено")
                    continue
                if key in ru and placeholders(final) != placeholders(ru[key]):
                    warnings.append(f"{where}: плейсхолдеры не совпадают с ru — пропущено")
                    continue
                if key in decisions and decisions[key]["final_text"] != final:
                    warnings.append(f"{where}: для ключа уже есть другое решение ({decisions[key]['finding_id']}) — оставлено первое")
                    continue
                decisions.setdefault(key, {
                    "key": key,
                    "issue_type": row.get("issue_type", ""),
                    "final_text": final,
                    "reviewer": (row.get("кто_проверил") or "").strip(),
                    "finding_id": row.get("id", ""),
                })
    return list(decisions.values()), warnings


def _findings_from_report(path: str | Path) -> list[Finding]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("findings", data) if isinstance(data, dict) else data
    fields = Finding.__dataclass_fields__
    return [Finding(**{k: v for k, v in it.items() if k in fields}) for it in items]


def main(argv=None) -> int:
    from ._load import build_context, read_arb

    p = argparse.ArgumentParser(prog="python -m locqa.sheet")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="report.json -> CSV для ревью")
    e.add_argument("--report", required=True)
    e.add_argument("--source", required=True)
    e.add_argument("--target", required=True)
    e.add_argument("--ref", help="intl_en.arb (колонка en)")
    e.add_argument("--out-dir", default="out/review")
    i = sub.add_parser("import", help="заполненные CSV -> decisions.csv для fix.py")
    i.add_argument("files", nargs="+")
    i.add_argument("--source", required=True)
    i.add_argument("--out", default="out/decisions.csv")
    a = p.parse_args(argv)

    if a.cmd == "export":
        ctx = build_context(a.source, a.target, en=a.ref)
        for path in export(ctx, _findings_from_report(a.report), a.out_dir):
            print(path)
        return 0

    decisions, warnings = load_decisions(a.files, read_arb(a.source)[0])
    for w in warnings:
        print("WARN", w, file=sys.stderr)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    _write(Path(a.out), decisions, DECISION_COLUMNS)
    by_reviewer: dict[str, int] = {}
    for d in decisions:
        by_reviewer[d["reviewer"]] = by_reviewer.get(d["reviewer"], 0) + 1
    print(f"{a.out}: {len(decisions)} правок, по носителям: {by_reviewer}, предупреждений: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
