"""Собирает сайт разметки: один HTML-файл без сервера, данные внутри файла.

    .venv/bin/python scripts/build_review_site.py

Файл out/review_site/review.html открывается двойным кликом. Проверяющий скачивает review_A_done.csv:
его принимают `python -m locqa.sheet import` (правки) и `scripts/precision_sample.py score` (precision).
В файле тексты кейса: не выкладывать в интернет и публичные репозитории.
"""
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa._load import build_context  # noqa: E402
from locqa.sheet import REVIEWERS, _uncell  # noqa: E402


def build(ctx, review_csv, out_path, reviewers=REVIEWERS) -> Path:
    index = {k: i for i, k in enumerate(ctx.order)}
    rows = []
    with open(review_csv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            i = index.get(r["key"])
            near = []
            if i is not None:
                near = [{"ru": ctx.ru[k], "kk": ctx.kk.get(k, "")} for k in ctx.order[max(0, i - 2): i] + ctx.order[i + 1: i + 3]]
            rows.append({
                "id": r["id"], "key": r["key"], "issue_type": r["issue_type"], "severity": r["severity"],
                "ru": _uncell(r["ru"]), "en": _uncell(r["en"]), "kk": _uncell(r["kk_сейчас"]),
                "evidence": _uncell(r["evidence"]), "suggestion": _uncell(r["suggestion"]),
                "reviewer": r["кто_проверил"], "section": ctx.sections.get(r["key"], ""), "near": near,
            })
    version = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    data = json.dumps({"rows": rows, "reviewers": list(reviewers), "version": version}, ensure_ascii=False)
    template = (Path(__file__).parent.parent / "locqa" / "review_template.html").read_text(encoding="utf-8")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # "</" внутри данных не должен закрыть тег <script>
    out_path.write_text(template.replace("/*DATA*/", data.replace("</", "<\\/")), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    ctx = build_context("data/intl_ru.arb", "data/intl_kk.arb", en="data/intl_en.arb", uz="data/intl_uz.arb")
    path = build(ctx, "out/review/review_all.csv", "out/review_site/review.html")
    print(path, f"{path.stat().st_size / 1024:.0f} KB")
