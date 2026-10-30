from types import SimpleNamespace

from locqa.checks import kazakh

GLOSSARY = [
    {"ru": "игрок", "kk": "ойыншы", "en": "player", "allowed_variants": [], "strict": ""},
    {"ru": "семья", "kk": "отбасы", "en": "family", "allowed_variants": [], "strict": "1"},
]


def make_ctx(pairs, glossary=None):
    """pairs: key -> (ru, kk)"""
    return SimpleNamespace(
        ru={k: v[0] for k, v in pairs.items()},
        kk={k: v[1] for k, v in pairs.items()},
        glossary=glossary or [],
        order=list(pairs),
    )


def by_type(findings, issue_type):
    return {f.key: f for f in findings if f.issue_type == issue_type}


# ------------------------------------------------------------------ orthography

def _ortho_ctx(extra):
    base = {f"ok{i}": ("Снова", "Қайта бастау") for i in range(5)}
    base.update(extra)
    return make_ctx(base)


def test_orthography_finds_russian_letter_typo():
    ctx = _ortho_ctx({"bad": ("Снова авторизация", "Кайта авторизация")})
    f = by_type(kazakh.check_orthography(ctx), "orthography")["bad"]
    assert f.suggestion == "Қайта авторизация"
    assert "кайта" in f.evidence and "қайта" in f.evidence
    assert f.severity == "medium"


def test_orthography_clean_file_has_no_findings():
    assert kazakh.check_orthography(_ortho_ctx({})) == []


def test_orthography_skips_russian_loanwords():
    # "торт" is rare and "төрт" is common, but торт is also a Russian word in ru.
    extra = {f"n{i}": ("Четыре", "Төрт") for i in range(4)}
    extra["cake"] = ("Торт", "Торт дайын")
    assert "cake" not in by_type(kazakh.check_orthography(_ortho_ctx(extra)), "orthography")


def test_orthography_mixed_latin_letters():
    ctx = _ortho_ctx({"mix": ("Перейди в раздел", "Бөлімiне өтiп")})
    f = by_type(kazakh.check_orthography(ctx), "orthography")["mix"]
    assert f.suggestion == "Бөліміне өтіп"
    assert f.confidence >= 0.95


# --------------------------------------------------------------- suffix_harmony

def test_suffix_after_placeholder():
    ctx = make_ctx({
        "a": ("Купить за {price}", "{price}-ге сатып алу"),
        "b": ("Подключение к {provider}", "{provider}ға қосылу"),
        "ok": ("Игрок {name} вошёл", "Ойыншы {name} кірді"),
        "ordinal": ("{place}-е место", "{place}-орын"),
    })
    found = by_type(kazakh.check_suffix_harmony(ctx), "suffix_harmony")
    assert set(found) == {"a", "b"}
    assert found["a"].severity == "high"
    assert "-ге" in found["a"].evidence and "-ке" in found["a"].evidence


# --------------------------------------- glossary_violation / inconsistent_term

def _term_ctx(extra):
    pairs = {f"p{i}": (f"Игрок номер {i}", f"Ойыншы нөмірі {i}") for i in range(10)}
    pairs.update({f"f{i}": ("Семья", "Отбасы") for i in range(3)})
    pairs.update(extra)
    return make_ctx(pairs, GLOSSARY)


def test_inconsistent_term_rare_rival_translation():
    ctx = _term_ctx({
        "r1": ("Передать игрокам", "Ойнаушыларға беру"),
        "r2": ("Искать игроков", "Ойнаушыларды іздеу"),
    })
    found = by_type(kazakh.check_glossary_terms(ctx), "inconsistent_term")
    assert set(found) == {"r1", "r2"}
    assert found["r2"].suggestion == "Ойыншыларды іздеу"
    assert "ойыншы" in found["r2"].evidence


def test_glossary_violation_on_strict_term():
    ctx = _term_ctx({"bad": ("Баланс семьи", "Жанұя балансы")})
    found = by_type(kazakh.check_glossary_terms(ctx), "glossary_violation")
    assert "bad" in found
    assert "отбасы" in found["bad"].evidence


def test_glossary_violation_russian_word_left_in_kazakh():
    ctx = _term_ctx({"ru_left": ("Баланс семьи", "семья балансы")})
    f = by_type(kazakh.check_glossary_terms(ctx), "glossary_violation")["ru_left"]
    assert f.suggestion == "отбасы балансы"


def test_russian_word_for_non_strict_term_is_inconsistent():
    ctx = _term_ctx({"ru_left": ("Имя игрока", "Игрок аты")})
    f = by_type(kazakh.check_glossary_terms(ctx), "inconsistent_term")["ru_left"]
    assert f.suggestion == "Ойыншы аты"


def test_glossary_checks_clean_file():
    assert kazakh.check_glossary_terms(_term_ctx({})) == []


def test_glossary_checks_skip_untranslated_and_copied_strings():
    ctx = _term_ctx({"empty": ("Баланс семьи", ""), "copy": ("Баланс семьи", "Баланс семьи")})
    assert kazakh.check_glossary_terms(ctx) == []


def test_established_alternative_goes_to_audit_not_report():
    alt = {f"alt{i}": (f"Лучший игрок {i}", f"Үздік қатысушы {i}") for i in range(3)}
    ctx = _term_ctx(alt)
    assert not by_type(kazakh.check_glossary_terms(ctx), "inconsistent_term")
    audit = kazakh.glossary_audit(ctx)
    assert {a["key"] for a in audit} == set(alt)


def test_check_entry_point_runs_all():
    ctx = _term_ctx({"s": ("За {price}", "{price}-ға")})
    types = {f.issue_type for f in kazakh.check(ctx)}
    assert "suffix_harmony" in types


def test_suffix_rephrase_moves_placeholder_after_colon():
    r = kazakh.rephrase_without_affix
    assert r("{provider}-ға қосылу мәселесі. Қайталау…") == "Қосылу мәселесі: {provider}. Қайталау…"
    assert r("{price}-ге сатып алу") == "Сатып алу: {price}"
    assert r("Пропусктың\n{id}-ға деңгейі қажет") == "Пропусктың\nдеңгейі қажет: {id}"


def test_suffix_rephrase_gives_up_on_hard_cases():
    r = kazakh.rephrase_without_affix
    assert r("{fromUser}-дан {toUser}-ға қарсы") is None   # two affixed placeholders in a clause
    assert r("<g>{bet}-ға GC</g> ставка") is None          # placeholder inside a tag
    assert r("Ойыншы {name} кірді") is None                # nothing to fix


def test_suffix_finding_carries_rephrase():
    ctx = make_ctx({"a": ("Купить за {price}", "{price}-ге сатып алу")})
    f = by_type(kazakh.check_suffix_harmony(ctx), "suffix_harmony")["a"]
    assert f.suggestion == "Сатып алу: {price}"
