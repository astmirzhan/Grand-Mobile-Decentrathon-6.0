from __future__ import annotations

from pathlib import Path

from locqa.arb import load_arb, update_arb_file
from locqa.checks.basic import check as basic_check
from locqa.fix import apply_decisions
from locqa.icu import extract_placeholders, validate_plural
from locqa.models import Context, Finding
from locqa.resolve import resolve_findings


def test_arb_preserves_repeated_comments_and_order(tmp_path: Path) -> None:
    arb_content = """{
  "@@locale": "ru",
  "@@comment": "Секция 1: Авторизация",
  "loginTitle": "Вход",
  "@loginTitle": {
    "description": "Заголовок экрана входа"
  },
  "currencySymbol": "₸",
  "@@comment": "Секция 2: Профиль",
  "logoutBtn": "Выйти"
}
"""
    arb_file = tmp_path / "intl_ru.arb"
    arb_file.write_text(arb_content, encoding="utf-8")

    parsed = load_arb(arb_file)
    assert parsed.order == ["loginTitle", "currencySymbol", "logoutBtn"]
    assert parsed.sections["loginTitle"] == "Секция 1: Авторизация"
    assert parsed.sections["logoutBtn"] == "Секция 2: Профиль"
    assert parsed.descriptions["loginTitle"] == "Заголовок экрана входа"
    assert parsed.values["currencySymbol"] == "₸"


def test_icu_placeholders_and_plural_validation() -> None:
    s = "{count, plural, one {{count} операция для {user}} other {{count} операций для {user}}}"
    assert extract_placeholders(s) == {"count", "user"}
    assert validate_plural(s, lang="kk") == []

    # Flutter accepts an other-only plural; one is optional.
    missing_one = "{count, plural, other {{count} элемент}}"
    errs = validate_plural(missing_one, lang="kk")
    assert errs == []

    # Несбалансированные скобки
    broken = "{count, plural, one {{count} элемент} other {{count} элементов}"
    assert validate_plural(broken, lang="kk")


def test_basic_checks_all_five_types() -> None:
    ctx = Context(
        ru={
            "k_untrans": "Продолжить",
            "k_same": "Настройки профиля",
            "k_brand": "Kaspi Gold",
            "k_uz": "Оплатить счёт",
            "k_ph": "Привет, {name}! У вас {count} бонусов",
            "k_plural": "{count, plural, one {{count} день} other {{count} дней}}",
        },
        kk={
            "k_untrans": "",
            "k_same": "Настройки профиля",
            "k_brand": "Kaspi Gold",  # бренд — не должно быть ошибкой
            "k_uz": "Hisobni to'lash",
            "k_ph": "Сәлем, {name}!",
            "k_plural": "{count, plural, one {{count} күн}}",
        },
        uz={"k_uz": "Hisobni to'lash"},
        order=["k_untrans", "k_same", "k_brand", "k_uz", "k_ph", "k_plural"],
    )

    findings = basic_check(ctx)
    by_key = {f.key: f for f in findings}

    assert by_key["k_untrans"].issue_type == "untranslated"
    assert by_key["k_same"].issue_type == "same_as_source"
    assert "k_brand" not in by_key
    assert by_key["k_uz"].issue_type == "wrong_language"
    assert by_key["k_ph"].issue_type == "placeholder_mismatch"
    assert "{count, name}" in by_key["k_ph"].evidence
    assert by_key["k_plural"].issue_type == "plural_mismatch"


def test_resolve_priority_and_fragments() -> None:
    f1 = Finding(key="k1", issue_type="orthography", source="а", target="б", evidence="e1", fragment="слово1")
    f2 = Finding(key="k1", issue_type="placeholder_mismatch", source="а", target="б", evidence="e2", fragment="ph")
    f3 = Finding(key="k1", issue_type="machine_translation_suspect", source="а", target="б", evidence="e3")

    res = resolve_findings([f1, f2, f3])
    # placeholder_mismatch — старшая, f1 остаётся т.к. другой fragment, f3 (fragment=None) отбрасывается
    assert [r.issue_type for r in res] == ["placeholder_mismatch", "orthography"]


def test_fix_preserves_formatting_and_guards_placeholders(tmp_path: Path) -> None:
    ru_arb = tmp_path / "intl_ru.arb"
    kk_arb = tmp_path / "intl_kk.arb"
    out_arb = tmp_path / "intl_kk_fixed.arb"
    csv_file = tmp_path / "decisions.csv"

    ru_arb.write_text(
        '{\n  "@@comment": "Header",\n  "hello": "Привет, {name}",\n  "missingKey": "Новый",\n  "bye": "Пока"\n}\n',
        encoding="utf-8",
    )
    kk_arb.write_text(
        '{\n  "@@comment": "Header",\n  "hello": "Привет, {name}",\n  "bye": "Пока"\n}\n',
        encoding="utf-8",
    )
    csv_file.write_text(
        "key,decision,suggestion,итоговый_текст,issue_type\n"
        "hello,❌,Сәлем,,placeholder_mismatch\n"  # отклонён ревьюером
        "bye,✅,Сау болыңыз,,same_as_source\n"
        "missingKey,✏️,,Жаңа,untranslated\n",
        encoding="utf-8",
    )

    applied, skipped = apply_decisions(csv_file, kk_arb, out_arb, source_arb=ru_arb)
    assert applied == 2
    assert skipped == 0

    fixed_text = out_arb.read_text(encoding="utf-8")
    assert '"@@comment": "Header"' in fixed_text
    assert '"missingKey": "Жаңа"' in fixed_text
    assert '"bye": "Сау болыңыз"' in fixed_text
    assert '"@bye": {"x-reviewed": true' in fixed_text

def test_fix_accepts_decisions_csv_from_sheet_import(tmp_path: Path) -> None:
    arb = tmp_path / "intl_kk.arb"
    arb.write_text('{\n  "buy": "кате"\n}\n', encoding="utf-8")
    decisions = tmp_path / "decisions.csv"
    decisions.write_text("key,issue_type,final_text,reviewer,finding_id\nbuy,orthography,қате,B,0001\n", encoding="utf-8")
    out = tmp_path / "fixed.arb"
    applied, _ = apply_decisions(decisions, arb, out)
    text = out.read_text(encoding="utf-8")
    assert applied == 1 and '"buy": "қате"' in text and '"x-reviewed": true' in text


def test_unused_plural_form_is_not_untranslated() -> None:
    ctx = Context(
        ru={"hourOne": "час", "hourFew": "часа", "hourOther": "часов", "title": "Магазин"},
        kk={"hourOne": "сағат", "hourOther": "сағат"},
        order=["hourOne", "hourFew", "hourOther", "title"],
    )
    untranslated = {f.key for f in basic_check(ctx) if f.issue_type == "untranslated"}
    assert untranslated == {"title"}


def test_apply_review_uses_human_verdicts() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from apply_review import apply_review

    base = {"severity": "medium", "source": "ru", "target": "kk", "evidence": "ev", "suggestion": "s", "confidence": 0.9}
    report = [{"key": "real", "issue_type": "orthography", **base}, {"key": "false", "issue_type": "orthography", **base},
              {"key": "open", "issue_type": "orthography", **base}]
    row = {"ru": "ru", "kk_сейчас": "kk", "evidence": "другой смысл", "severity": "low", "suggestion": "s"}
    reviewed = {
        ("real", "orthography"): {**row, "key": "real", "issue_type": "orthography", "verdict": "1", "итоговый_текст": "свой"},
        ("false", "orthography"): {**row, "key": "false", "issue_type": "orthography", "verdict": "0"},
        ("extra", "machine_translation_suspect"): {**row, "key": "extra", "issue_type": "machine_translation_suspect", "verdict": "1"},
        ("drop", "machine_translation_suspect"): {**row, "key": "drop", "issue_type": "machine_translation_suspect", "verdict": "0"},
    }
    out = {f.key: f for f in apply_review(report, reviewed)}
    assert set(out) == {"real", "open", "extra"}
    assert out["real"].reviewed_by_human and out["real"].suggestion == "свой"
    assert out["extra"].reviewed_by_human and not out["open"].reviewed_by_human
