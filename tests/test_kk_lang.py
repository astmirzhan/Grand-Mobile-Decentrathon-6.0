from locqa.lang import kk


def test_letter_pairs_cover_kazakh_letters():
    covered = set("".join(kk.LETTER_PAIRS.values()))
    assert covered == kk.KK_LETTERS


def test_plural_categories():
    assert kk.PLURAL_CATEGORIES == ["one", "other"]


def test_stem_drops_alternating_final_and_soft_sign():
    assert kk.stem("көлік") == "көлі"
    assert kk.stem("сыйлық") == "сыйлы"
    assert kk.stem("инвентарь") == "инвентар"
    assert kk.stem("үй") == "үй"


def test_word_has_stem_handles_inflection_and_short_stems():
    assert kk.word_has_stem("отбасының", "отбасы")
    assert kk.word_has_stem("көлігі", "көлік")
    assert kk.word_has_stem("үйге", "үй")
    assert not kk.word_has_stem("үйрену", "үй")
    assert not kk.word_has_stem("ойнаушы", "ойыншы")


def test_harmonize_vowel_and_consonant_rules():
    assert kk.harmonize("үй", "dative") == "ге"
    assert kk.harmonize("қала", "dative") == "ға"
    assert kk.harmonize("кітап", "dative") == "қа"
    assert kk.harmonize("адам", "genitive") == "ның"
    assert kk.harmonize("мектеп", "genitive") == "тің"
    assert kk.harmonize("жол", "plural") == "дар"
    assert kk.harmonize("жол", "instrumental") == "мен"
    assert kk.harmonize("қыз", "instrumental") == "бен"


def test_split_and_inflect_roundtrip():
    assert kk.split_affixes("ойнаушыларды") == ("ойнаушы", ["лар", "ды"])
    assert kk.split_affixes("отбасының") == ("отбасы", ["ның"])
    assert kk.inflect("ойыншы", ["лар", "ды"]) == "ойыншыларды"
    assert kk.inflect("скин", ["лар"]) == "скиндер"


def test_mixed_script():
    assert kk.is_mixed_script("бөлімiне")  # Latin i
    assert not kk.is_mixed_script("бөліміне")
    assert not kk.is_mixed_script("Grand")
