"""Generate shared test vectors for the Python and Dart Kazakh affix helpers.

    python scripts/gen_kk_affix_vectors.py

Writes integrations/flutter/kk_affix/test/vectors.json. The Dart test reads it, so both
implementations are checked against the same expected forms.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from locqa.lang.kk_runtime import CASES, inflect_value  # noqa: E402

OUT = ROOT / "integrations/flutter/kk_affix/test/vectors.json"

VALUES = [
    # Kazakh names: back / front vowels, final voiceless, nasal, sonorant
    "Айдос", "Әлия", "Айгерім", "Мадина", "Ерлан", "Нұрсұлтан", "Дәулет", "Әсел", "Бекзат",
    "Жұлдыз", "Ақбота", "Серік", "Төлеген", "Ұлжан", "Қайрат", "ҚАЙРАТ",
    # Russian names
    "Игорь", "Сергей", "Виктор", "Ольга",
    # numbers: units, tens, hundreds, thousands, decimals
    "0", "1", "2", "3", "5", "6", "7", "9", "10", "20", "40", "50", "100", "250", "1000",
    "2000", "1500", "1000000", "1.5", "99,9",
    # Latin: brands, providers, nicknames
    "Google", "Apple", "Kaspi", "Discord", "Telegram", "Timur", "Andy", "Player123", "VK Pay",
]


def build() -> list[dict]:
    return [{"value": v, "case": c, "expected": inflect_value(v, c)} for v in VALUES for c in CASES]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(VALUES) * len(CASES)} vectors -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
