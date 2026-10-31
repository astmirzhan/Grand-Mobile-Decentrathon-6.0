from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import pkgutil
import sys
from pathlib import Path
from typing import Any

import locqa.checks
from locqa import llm as llm_mod
from locqa.arb import load_arb
from locqa.checks import llm_checks
from locqa.fix import apply_decisions
from locqa.models import CheckFunc, Context, Finding
from locqa.report import write_html_report, write_json_report
from locqa.resolve import resolve_findings
from locqa.sheet import export as export_review
from locqa.suggest import suggest


def load_glossary_entries(path: str | Path | None) -> list[dict[str, Any]]:
    candidates = [Path(path)] if path else []
    candidates.extend([Path("glossary.csv"), Path("data/glossary.csv")])
    target_path = next((p for p in candidates if p.exists()), None)
    if not target_path:
        return []

    try:
        from locqa import glossary as gl
        for fn_name in ("load_glossary", "load", "read_glossary"):
            fn = getattr(gl, fn_name, None)
            if callable(fn):
                return fn(target_path)
    except Exception:
        pass

    with target_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            d = dict(row)
            if "allowed_variants" in d and isinstance(d["allowed_variants"], str):
                d["allowed_variants"] = [
                    x.strip() for x in d["allowed_variants"].split("|") if x.strip()
                ]
            rows.append(d)
        return rows


def discover_checks() -> list[tuple[str, CheckFunc]]:
    """Все проверки без LLM; llm_checks вызывается отдельно, ей нужен клиент и skip_keys."""
    discovered: list[tuple[str, CheckFunc]] = []
    package_path = locqa.checks.__path__
    prefix = locqa.checks.__name__ + "."

    for _, mod_name, is_pkg in pkgutil.iter_modules(package_path, prefix):
        if is_pkg:
            continue
        if mod_name.endswith(".llm_checks"):
            continue
        module = importlib.import_module(mod_name)
        check_fn = getattr(module, "check", None)
        if callable(check_fn):
            discovered.append((mod_name, check_fn))

    return discovered


def cmd_check(args: argparse.Namespace) -> int:
    ru_doc = load_arb(args.source)
    kk_doc = load_arb(args.target)
    # команда из ТЗ не передаёт --en и --uz: берём соседние файлы, они усиливают проверки
    uz_path = args.uz or Path(args.source).with_name("intl_uz.arb")
    en_path = args.en or Path(args.source).with_name("intl_en.arb")
    uz_doc = load_arb(uz_path) if Path(uz_path).exists() and Path(uz_path) != Path(args.target) else None
    en_doc = load_arb(en_path) if Path(en_path).exists() and Path(en_path) != Path(args.target) else None

    ctx = Context(
        ru=ru_doc.values,
        kk=kk_doc.values,
        en=en_doc.values if en_doc else {},
        uz=uz_doc.values if uz_doc else {},
        order=ru_doc.order,
        descriptions=ru_doc.descriptions,
        sections=ru_doc.sections,
        glossary=load_glossary_entries(args.glossary),
        meta=ru_doc.meta,
        no_llm=args.no_llm,
    )

    all_findings: list[Finding] = []
    for mod_name, check_fn in discover_checks():
        try:
            res = check_fn(ctx)
            if res:
                all_findings.extend(res)
                print(f"[OK] {mod_name}: найдено {len(res)}")
        except Exception as exc:
            print(f"[ERROR] Ошибка в модуле проверки {mod_name}: {exc}", file=sys.stderr)

    # --no-llm отключает только запросы: кодовые доказательства (повторяющиеся хвосты) работают всегда
    llm = llm_mod.configure(
        enabled=False if args.no_llm else None,
        offline=args.offline or None,
        workers=int(os.environ.get("LOCQA_WORKERS", 4)),
        batch_size=int(os.environ.get("LOCQA_BATCH", 25)),
    )
    llm_found, meaning = llm_checks.check_with_meaning(ctx, llm, skip_keys={f.key for f in all_findings})
    print(f"[OK] locqa.checks.llm_checks: найдено {len(llm_found)}, ошибки смысла для носителей: {len(meaning)}")
    all_findings.extend(llm_found)

    resolved = resolve_findings(all_findings, key_order=ru_doc.order)
    taken = {f.key for f in resolved}
    meaning = [f for f in resolve_findings(meaning, key_order=ru_doc.order) if f.key not in taken]
    suggest_stats = suggest(ctx, resolved + meaning, llm)

    out_arg = Path(args.out)
    if out_arg.suffix.lower() == ".json":
        json_path = out_arg
        html_path = out_arg.with_suffix(".html")
    elif out_arg.suffix.lower() == ".html":
        html_path = out_arg
        json_path = out_arg.with_suffix(".json")
    else:
        out_arg.mkdir(parents=True, exist_ok=True)
        json_path = out_arg / "report.json"
        html_path = out_arg / "report.html"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_report(resolved, json_path)
    write_html_report(resolved, html_path)

    # стоимость LLM — требование ТЗ; report.json остаётся списком находок по схеме кейса
    summary_path = json_path.with_suffix(".llm.json")
    summary_path.write_text(
        json.dumps({"llm": llm.summary(), "suggest": suggest_stats, "meaning_for_review": len(meaning)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.review_dir:
        for path in export_review(ctx, resolved + meaning, args.review_dir):
            print(f"Таблица ревью: {path}")

    print(f"Итого после дедупликации (resolve): {len(resolved)} проблем. Отчёты: {json_path}, {html_path}")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    applied, skipped = apply_decisions(
        decisions_csv=args.decisions,
        target_arb=args.target,
        out_arb=args.out,
        source_arb=args.source,
        default_reviewer=args.reviewer,
        fallback_meta=args.fallback_meta,
    )
    print(f"Применено правок: {applied}, пропущено/отклонено защитой: {skipped}. Результат: {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="locqa", description="Flutter ARB Localization QA & Fixer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_check = subparsers.add_parser("check", help="Запустить проверки локализации")
    p_check.add_argument("--source", required=True, help="Путь к исходному ARB (intl_ru.arb)")
    p_check.add_argument("--target", required=True, help="Путь к целевому ARB (intl_kk.arb)")
    p_check.add_argument("--uz", default=None, help="Путь к узбекскому ARB (intl_uz.arb)")
    p_check.add_argument("--en", default=None, help="Путь к английскому ARB (intl_en.arb)")
    p_check.add_argument("--glossary", default=None, help="Путь к glossary.csv")
    p_check.add_argument("--out", default="report.json", help="Путь к выходному файлу/папке отчёта")
    p_check.add_argument("--no-llm", action="store_true", help="Без запросов к LLM, только кодовые проверки")
    p_check.add_argument("--offline", action="store_true", help="Только готовые ответы из кэша, без запросов к API")
    p_check.add_argument("--review-dir", default=None, help="Папка для таблиц ревью A/B/C")
    p_check.set_defaults(func=cmd_check)

    p_fix = subparsers.add_parser("fix", help="Применить ревью-решения из CSV к ARB")
    p_fix.add_argument("--decisions", required=True, help="Путь к decisions.csv")
    p_fix.add_argument("--target", required=True, help="Путь к исходному intl_kk.arb")
    p_fix.add_argument("--out", required=True, help="Путь для сохранения intl_kk_fixed.arb")
    p_fix.add_argument("--source", default=None, help="Путь к intl_ru.arb")
    p_fix.add_argument("--reviewer", default="A", help="Код ревьюера (по умолчанию A)")
    p_fix.add_argument("--fallback-meta", action="store_true", help="Использовать @@x-reviewed вместо @key")
    p_fix.set_defaults(func=cmd_fix)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())