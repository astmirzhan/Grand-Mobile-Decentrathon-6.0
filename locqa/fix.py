from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from locqa.arb import load_arb, update_arb_file
from locqa.validation import validate_text


def _pick_col(row: dict[str, str], candidates: tuple[str, ...], strip: bool = True) -> str:
    for c in candidates:
        for k, v in row.items():
            if k and k.strip().lower() == c.lower():
                return (v or "").strip() if strip else (v or "")
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
    ru_doc = load_arb(source_arb) if source_arb else None
    kk_doc = load_arb(target_arb)

    updates: dict[str, str] = {}
    review_meta: dict[str, dict[str, Any]] = {}
    skipped = 0

    with Path(decisions_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = _pick_col(row, ("key", "ключ"))
            decision = _pick_col(row, ("decision", "status", "решение", "статус"))
            suggestion = _pick_col(row, ("suggestion", "предложение"), strip=False)
            final_text = _pick_col(row, ("итоговый_текст", "final_text", "final", "итог"), strip=False)
            issue_type = _pick_col(row, ("issue_type", "тип", "issue")) or "manual_review"
            reviewer = _pick_col(row, ("reviewer", "ревьюер", "кто_проверил")) or default_reviewer

            if not key:
                continue
            if not decision and not final_text:
                continue

            # decisions.csv из sheet import: там уже только принятые правки, колонки решения нет
            if not decision:
                new_text = final_text
            elif "✅" in decision:
                new_text = final_text if final_text.strip() else suggestion
            elif "✏️" in decision or "✏" in decision:
                new_text = final_text
            else:
                continue

            if not new_text.strip():
                print(f"[WARN] Ключ '{key}': пустой текст для решения {decision}, пропуск.", file=sys.stderr)
                skipped += 1
                continue

            if ru_doc and key not in ru_doc.values:
                print(f"[WARN] Неизвестный ключ '{key}', пропуск.", file=sys.stderr)
                skipped += 1
                continue
            ref_source = ru_doc.values[key] if ru_doc else _pick_col(row, ("source", "ru"), strip=False)
            errors = validate_text(ref_source, new_text)
            if errors:
                print(f"[WARN] {key}: {'; '.join(errors)} — правка отклонена", file=sys.stderr)
                skipped += 1
                continue
            if key in updates and updates[key] != new_text:
                raise ValueError(f"Conflicting decisions for {key}")
            if kk_doc.values.get(key) == new_text:
                continue
            updates[key] = new_text
            existing_meta = dict(kk_doc.meta.get(key, {}))
            existing_meta.update(
                {
                    "x-reviewed": (row.get("reviewed_by_human", "true").lower() == "true"),
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
