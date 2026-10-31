import csv
import json
import re
import sys
from pathlib import Path

from conftest import make_ctx

from locqa.models import Finding
from locqa.sheet import export

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from build_review_site import build  # noqa: E402


def test_site_embeds_rows_safely(tmp_path):
    ctx = make_ctx({"a": ("-5 </script> {n}", "қате {n}"), "b": ("Текст", "Мәтін")})
    findings = [Finding(k, "orthography", "medium", ctx.ru[k], ctx.kk[k], "ev", ctx.kk[k] + "!", 0.9) for k in ctx.order]
    export(ctx, findings, tmp_path)
    html = build(ctx, tmp_path / "review_all.csv", tmp_path / "site" / "review.html").read_text(encoding="utf-8")
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(raw)  # тег </script> из текста строки не обрывает данные
    rows = {r["key"]: r for r in data["rows"]}
    assert rows["a"]["ru"] == "-5 </script> {n}" and rows["a"]["reviewer"] == "A"
    assert rows["b"]["near"] == [{"ru": "-5 </script> {n}", "kk": "қате {n}"}]
