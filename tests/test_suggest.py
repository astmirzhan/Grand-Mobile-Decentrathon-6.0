from conftest import fake_llm, make_ctx

from locqa.models import Finding
from locqa.suggest import restore_placeholders, suggest, suffix_after_placeholder, validate


def F(key, ctx, issue, suggestion=None):
    return Finding(key, issue, "high", ctx.ru.get(key, ""), ctx.kk.get(key, ""), "ev", suggestion, 0.9)


def test_validate_rules():
    assert validate("Привет, {name}", "x", "Сәлем, {name}", "same_as_source", "greet") is None
    assert validate("Привет, {name}", "x", "Сәлем", "same_as_source", "greet") == "плейсхолдеры не совпадают с ru"
    assert validate("Отправлено {name}", "x", "{name}-ға жіберілді", "x", "k") == "аффикс сразу после плейсхолдера"
    assert validate("Купить", "x", "Сатып алу үшін басу", "length_overflow", "buyButton").startswith("длиннее")
    assert validate("a", "same", "same", "orthography", "k") == "совпадает с текущим kk"


def test_suffix_detection():
    assert suffix_after_placeholder("{count}ден астам")
    assert suffix_after_placeholder("{name}-ға")
    assert not suffix_after_placeholder("Алушы: {name}")
    assert not suffix_after_placeholder("{count} дана")


def test_restore_placeholders_by_code():
    assert restore_placeholders("Цена {cost}", "Бағасы {price}") == "Бағасы {cost}"
    assert restore_placeholders("{a} и {b}", "{a}") is None


def test_suggest_fills_and_validates(tmp_path):
    ctx = make_ctx({
        "ph": ("Цена {cost}", "Бағасы {price}"),
        "copy": ("Принять", "Принять"),
        "bad": ("Отправлено {name}", "Отправлено {name}"),
        "keep": ("Дом", "Үй"),
    })
    findings = [F("ph", ctx, "placeholder_mismatch"), F("copy", ctx, "same_as_source"),
                F("bad", ctx, "same_as_source"), F("keep", ctx, "orthography", suggestion="Үй-жай")]

    def answer(it, system):
        return {"copy": {"suggestion": "Қабылдау", "note": ""},
                "bad": {"suggestion": "{name}-ға жіберілді", "note": ""}}.get(it["key"])

    llm, calls = fake_llm(answer, tmp_path)
    stats = suggest(ctx, findings, llm)
    assert [f.suggestion for f in findings] == ["Бағасы {cost}", "Қабылдау", None, "Үй-жай"]
    assert stats["code"] == 1 and stats["llm_accepted"] == 1
    assert stats["rejected"] == {"аффикс сразу после плейсхолдера": 1}
    assert len(calls) == 1  # уже валидные предложения и кодовые фиксы в LLM не уходят


def test_match_case_keeps_caps_and_placeholders():
    from locqa.suggest import match_case
    assert match_case("1 ДЕНЬ", "1 КҮН бөліміне өту", "1 күн") == "1 КҮН"
    assert match_case("КУПИТЬ ЗА {cost}", "САТЫП АЛУ {cost}", "сатып алу {cost}") == "САТЫП АЛУ {cost}"
    assert match_case("Купить", "Сатып алу үшін", "сатып алу") == "сатып алу"


def test_translation_equal_to_ru_rejected():
    assert validate("Наличные", "Наличные", "наличные", "same_as_source", "k") == "вариант совпадает с ru — это не перевод"
    assert validate("Баланс", "қолма-қол ақша", "Баланс", "length_overflow", "balance") is None
