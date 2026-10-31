import json
from pathlib import Path

import pytest

from locqa.lang.kk_runtime import affix, inflect_value, number_word, spoken_tail
from scripts import gen_kk_affix_vectors

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value, case, expected", [
    ("Айдос", "dative", "Айдосқа"),
    ("Әлия", "dative", "Әлияға"),
    ("Айгерім", "dative", "Айгерімге"),
    ("Ерлан", "instrumental", "Ерланмен"),
    ("Жұлдыз", "instrumental", "Жұлдызбен"),
    ("Серік", "ablative", "Серіктен"),
    ("5", "ablative", "5-тен"),
    ("6", "dative", "6-ға"),
    ("40", "dative", "40-қа"),
    ("100", "dative", "100-ге"),
    ("1000", "ablative", "1000-нан"),
    ("Google", "dative", "Google-ға"),
    ("Kaspi", "dative", "Kaspi-ге"),
    ("ҚАЙРАТ", "dative", "ҚАЙРАТҚА"),
])
def test_inflect_value(value, case, expected):
    assert inflect_value(value, case) == expected


def test_number_words_take_the_last_spoken_part():
    assert [number_word(n) for n in (0, 7, 20, 300, 5000, 2_000_000)] == \
        ["нөл", "жеті", "жиырма", "жүз", "мың", "миллион"]
    assert spoken_tail("1.5") == "бес"
    assert spoken_tail("Игорь") == "игор"


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError):
        affix("Айдос", "vocative")


def test_dart_vectors_are_up_to_date():
    path = ROOT / "integrations/flutter/kk_affix/test/vectors.json"
    assert json.loads(path.read_text(encoding="utf-8")) == gen_kk_affix_vectors.build(), \
        "run: python scripts/gen_kk_affix_vectors.py"
