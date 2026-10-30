from pathlib import Path

from locqa import glossary as gl

ROOT = Path(__file__).resolve().parents[1]


def test_load_glossary_parses_variants(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("ru,kk,en,comment,allowed_variants\n"
                 "семья,отбасы,family,,\n"
                 "Grand Coins,Grand Coins,Grand Coins,brand,GC|ГК\n"
                 ",,,,\n", encoding="utf-8")
    rows = gl.load_glossary(p)
    assert [r["ru"] for r in rows] == ["семья", "Grand Coins"]
    assert rows[0]["allowed_variants"] == []
    assert rows[1]["allowed_variants"] == ["GC", "ГК"]


def test_project_glossary_is_valid():
    rows = gl.load_glossary(ROOT / "glossary.csv")
    assert len(rows) >= 50
    assert all(r["ru"] and r["kk"] and r["en"] for r in rows)
    ru_terms = [r["ru"].lower() for r in rows]
    assert len(ru_terms) == len(set(ru_terms)), "duplicate ru terms"
    by_ru = {r["ru"]: r for r in rows}
    assert by_ru["семья"]["kk"] == "отбасы"
    assert "ГК" in by_ru["Grand Coins"]["allowed_variants"]


def test_ru_stem_matching_respects_word_forms():
    assert gl.ru_has_term("Баланс семьи", "семья")
    assert gl.ru_has_term("Права фракции", "фракция")
    assert gl.ru_has_term("Купить автомобили", "автомобиль")
    assert not gl.ru_has_term("Банкомат", "бан")
    assert not gl.ru_has_term("Обработка", "работа")
    assert gl.ru_has_term("Обменяйте Grand Coins на бензин", "Grand Coins")


def test_kk_term_matching():
    entry = {"ru": "семья", "kk": "отбасы", "allowed_variants": []}
    assert gl.kk_has_any("Отбасының балансы", entry)
    assert not gl.kk_has_any("Жанұяның балансы", entry)
    gc = {"ru": "Grand Coins", "kk": "Grand Coins", "allowed_variants": ["GC"]}
    assert gl.kk_has_any("250 GC қажет", gc)
