from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from locqa.arb import load_arb, update_arb_file
from locqa.icu import check_balanced_braces, extract_placeholders


def _pick_col(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for c in candidates:
        for k, v in row.items():
            if k and k.strip().lower() == c.lower():
                return (v or "").strip()
    return ""


def apply_decisions(
    decisions_csv: str | Path,
    target_arb: str | Path,
    out_arb: str | Path,
    source_arb: str | Path | None = None,
    default_reviewer: str = "A",
    fallback_meta: bool = False,
) -> tuple[int, int]:
    """
    Читает CSV решений (берёт только ✅ и ✏️), проверяет совпадение плейсхолдеров с ru
    и построчно записывает исправленный ARB.
    Возвращает (applied_count, skipped_count).
    """
    ru_doc = load_arb(source_arb) if source_arb and Path(source_arb).exists() else None
    kk_doc = load_arb(target_arb)

    updates: dict[str, str] = {}
    review_meta: dict[str, dict[str, Any]] = {}
    skipped = 0

    with Path(decisions_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = _pick_col(row, ("key", "ключ"))
            decision = _pick_col(row, ("decision", "status", "решение", "статус"))
            suggestion = _pick_col(row, ("suggestion", "предложение"))
            final_text = _pick_col(row, ("итоговый_текст", "final_text", "final", "итог"))
            issue_type = _pick_col(row, ("issue_type", "тип", "issue")) or "manual_review"
            reviewer = _pick_col(row, ("reviewer", "ревьюер")) or default_reviewer

            if not key:
                continue
            if not decision and not final_text:
                continue

            # decisions.csv из sheet import: там уже только принятые правки, колонки решения нет
            if not decision:
                new_text = final_text
            elif "✅" in decision:
                new_text = suggestion
            elif "✏️" in decision or "✏" in decision:
                new_text = final_text
            else:
                continue

            if not new_text:
                print(f"[WARN] Ключ '{key}': пустой текст для решения {decision}, пропуск.", file=sys.stderr)
                skipped += 1
                continue

            # Защита: проверяем баланс скобок и совпадение плейсхолдеров с ru
            if not check_balanced_braces(new_text):
                print(
                    f"[WARN] Ключ '{key}': несбалансированные фигурные скобки в '{new_text}', правка отклонена!",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            ref_source = (
                ru_doc.values.get(key)
                if ru_doc and key in ru_doc.values
                else _pick_col(row, ("source", "ru"))
            )
            if ref_source:
                ru_ph = extract_placeholders(ref_source)
                new_ph = extract_placeholders(new_text)
                if ru_ph != new_ph:
                    print(
                        f"[WARN] Ключ '{key}': не совпали плейсхолдеры! В ru {sorted(ru_ph)}, в правке {sorted(new_ph)}. Правка отклонена!",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue

            updates[key] = new_text
            existing_meta = dict(kk_doc.meta.get(key, {}))
            existing_meta.update(
                {
                    "x-reviewed": True,
                    "x-reviewer": reviewer,
                    "x-issue": issue_type,
                }
            )
            review_meta[key] = existing_meta

    update_arb_file(
        target_path=target_arb,
        out_path=out_arb,
        updates=updates,
        ru_order=ru_doc.order if ru_doc else None,
        review_meta=review_meta,
        fallback_meta=fallback_meta,
    )
    return len(updates), skipped