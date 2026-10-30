from conftest import fake_llm, make_ctx

from locqa.checks import llm_checks
from locqa.llm import LLM

ROWS = {
    "shopBuyButton": ("Купить", "Сатып алу үшін басыңыз"),  # кнопка, раздута
    "shopTitle": ("Магазин", "Дүкен"),  # нормально
    "longDesc": (
        "Здесь вы можете купить автомобиль и улучшить его",
        "Мұнда сіз көлік сатып алып, оны жақсарта аласыз",
    ),
    "calque": ("Принять участие в событии", "Оқиғада қатысуды қабылдау"),
}


def test_length_candidates_by_code():
    keys = [k for k, _ in llm_checks.length_candidates(make_ctx(ROWS))]
    assert keys == ["shopBuyButton"]


def test_length_overflow_without_llm_needs_proof(tmp_path):
    # кандидат по длине есть, но без LLM и без повторяющегося хвоста это не находка
    assert llm_checks.check_length_overflow(make_ctx(ROWS), LLM(enabled=False, cache_dir=tmp_path)) == []


def test_length_overflow_confirmed_with_valid_short_variant(tmp_path):
    llm, _ = fake_llm(lambda it, s: {"is_short_ui": True, "kind": "padding", "too_long": True, "short_kk": "Сатып алу",
                                     "extra_words": "үшін басыңыз",
                                     "confidence": 0.9, "reason": "лишние слова"}, tmp_path)
    [f] = llm_checks.check_length_overflow(make_ctx(ROWS), llm)
    assert f.suggestion == "Сатып алу" and f.confidence == 0.9 and "лишние слова" in f.evidence


def test_length_overflow_rejected_by_llm(tmp_path):
    llm, _ = fake_llm(lambda it, s: {"is_short_ui": False, "too_long": True, "short_kk": "", "extra_words": "",
                                     "confidence": 0.9, "reason": ""}, tmp_path)
    assert llm_checks.check_length_overflow(make_ctx(ROWS), llm) == []


def test_mt_requires_fragment_in_kk_and_threshold(tmp_path):
    def answer(it, s):
        if it["id"] == "calque":
            return {"kind": "calque", "fragment": "Оқиғада қатысуды", "problem": "калька",
                    "suggestion": "Оқиғаға қатысу", "confidence": 0.9}
        if it["id"] == "longDesc":  # выдуманный фрагмент — должен отсеяться
            return {"kind": "wrong_meaning", "fragment": "нет такого", "problem": "x", "suggestion": "", "confidence": 0.95}
        return {"kind": "calque", "fragment": "", "problem": "", "suggestion": "", "confidence": 0.85}

    llm, _ = fake_llm(answer, tmp_path)
    [f] = llm_checks.check_machine_translation(make_ctx(ROWS), llm)
    assert f.key == "calque" and f.severity == "low" and f.suggestion == "Оқиғаға қатысу"


def test_mt_skips_known_keys_and_short_strings(tmp_path):
    seen = []
    llm, _ = fake_llm(lambda it, s: seen.append(it["id"]) or None, tmp_path)
    llm_checks.check_machine_translation(make_ctx(ROWS), llm, skip_keys={"calque"})
    assert seen == ["shopBuyButton", "shopTitle", "longDesc"]  # calque пропущен


def test_length_skips_when_uzbek_is_as_long():
    ctx = make_ctx({"startIn": ("до начала", "басталуына дейін")})
    assert [k for k, _ in llm_checks.length_candidates(ctx)] == ["startIn"]
    ctx.uz = {"startIn": "boshlanishiga qadar"}  # uz такой же длины -> нормальная морфология
    assert llm_checks.length_candidates(ctx) == []


def test_length_requires_extra_words_present_in_kk(tmp_path):
    llm, _ = fake_llm(lambda it, s: {"is_short_ui": True, "kind": "padding", "too_long": True, "short_kk": "Сатып алу",
                                     "extra_words": "выдумано", "confidence": 0.9, "reason": ""}, tmp_path)
    assert llm_checks.check_length_overflow(make_ctx(ROWS), llm) == []


def test_recurring_tail_found_without_llm(tmp_path):
    ctx = make_ctx({
        "win": ("Победа", "Жеңіс режимін қосу және жалғастыру"),
        "other": ("РАЗНОЕ", "Басқа режимін қосу және жалғастыру"),
        "ok1": ("Купить автомобиль?", "Көлік сатып алу керек пе?"),
        "ok2": ("Купить дом?", "Үй сатып алу керек пе?"),
    })
    assert llm_checks.recurring_tails(ctx, ["ok1", "ok2"]) == {}
    assert llm_checks.recurring_tails(ctx, ["win", "other"]) == {
        "win": "режимін қосу және жалғастыру", "other": "режимін қосу және жалғастыру"}
    f = {x.key: x for x in llm_checks.check_length_overflow(ctx, LLM(enabled=False, cache_dir=tmp_path))}
    assert set(f) == {"win", "other"}  # ok2 — кандидат по длине, но без хвоста это не доказательство
    assert f["win"].confidence == 0.85 and f["win"].suggestion == "Жеңіс"


def test_fragment_omission_complaint_dropped(tmp_path):
    ctx = make_ctx({
        "buyFor": ("Купить за", "сатып алу"),
        "before": ("до", "қазір"),
    })

    def answer(it, s):
        if it["id"] == "buyFor":
            return {"kind": "wrong_meaning", "fragment": "сатып алу", "problem": "потеряно «за»",
                    "suggestion": "сатып алу үшін", "confidence": 0.99}
        return {"kind": "wrong_meaning", "fragment": "қазір", "problem": "kk говорит «сейчас»",
                "suggestion": "дейін", "confidence": 0.99}

    llm, _ = fake_llm(answer, tmp_path)
    assert [f.key for f in llm_checks.check_machine_translation(ctx, llm)] == ["before"]


def test_meaning_errors_stay_out_of_report(tmp_path):
    ctx = make_ctx({"cancel": ("Отмена действия сейчас", "Әрекетті бастау дәл қазір"),
                    "calque": ("Принять участие в событии", "Оқиғада қатысуды қабылдау")})

    def answer(it, s):
        if it["id"] == "cancel":
            return {"kind": "wrong_meaning", "fragment": "бастау", "problem": "kk говорит «начать»",
                    "suggestion": "Әрекеттен бас тарту", "confidence": 0.99}
        return {"kind": "calque", "fragment": "Оқиғада қатысуды", "problem": "калька",
                "suggestion": "Оқиғаға қатысу", "confidence": 0.95}

    llm, _ = fake_llm(answer, tmp_path)
    report, meaning = llm_checks.check_with_meaning(ctx, llm)
    assert [f.key for f in report] == ["calque"] and [f.key for f in meaning] == ["cancel"]
    assert [f.key for f in llm_checks.check(ctx, llm)] == ["calque"]
