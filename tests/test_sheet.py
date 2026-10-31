import csv

from conftest import make_ctx

from locqa.models import Finding
from locqa.sheet import export, load_decisions


def _fill(path, decisions: dict[str, tuple[str, str]]):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["key"] in decisions:
            r["решение"], r["итоговый_текст"] = decisions[r["key"]]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_export_import_roundtrip(tmp_path):
    ctx = make_ctx({f"k{i}": (f"Текст {i} {{n}}", f"Мәтін {i} {{n}}") for i in range(6)} | {"neg": ("-5 очков", "-5 ұпай")},
                   en={"k0": "Text 0"})
    findings = [Finding(k, "orthography", "medium", ctx.ru[k], ctx.kk[k], "ev", ctx.kk[k] + "!", 0.9) for k in ctx.order]
    paths = export(ctx, findings, tmp_path)
    assert [p.name for p in paths] == ["review_all.csv", "review_A.csv", "review_B.csv", "review_C.csv"]

    parts = [list(csv.DictReader(open(p, encoding="utf-8"))) for p in paths[1:]]
    assert sorted(len(p) for p in parts) == [2, 2, 3]
    neg = next(r for r in csv.DictReader(open(paths[0], encoding="utf-8")) if r["key"] == "neg")
    assert neg["ru"] == "'-5 очков"  # защита от формул в Google Таблицах

    _fill(paths[1], {"k0": ("✅", ""), "k3": ("✏", "Свой {n}"), "neg": ("✅", "")})
    _fill(paths[2], {"k1": ("❌", ""), "k4": ("✏", "без плейсхолдера")})
    decisions, warnings = load_decisions(paths[1:], ctx.ru)
    got = {d["key"]: (d["final_text"], d["reviewer"]) for d in decisions}
    assert got["k0"] == ("Мәтін 0 {n}!", "A")
    assert got["k3"][0] == "Свой {n}"
    assert "k1" not in got and "k4" not in got
    assert any("плейсхолдеры" in w for w in warnings)
    assert got["neg"][0] == "-5 ұпай!"  # апостроф-защита снята при импорте
