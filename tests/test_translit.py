import json

from locqa.lang.translit import to_latin
from scripts import translit_kk


def test_kazakh_letters():
    assert to_latin("Қазақстан") == "Qazaqstan"
    assert to_latin("Ұяшық") == "Ūiaşyq"
    assert to_latin("Ішкі өнім") == "Işkı önım"
    assert to_latin("Ғимарат һәм") == "Ğimarat häm"


def test_uppercase_words_keep_dotted_i():
    assert to_latin("ШЫҒУ") == "ŞYĞU"
    assert to_latin("ТИІН") == "TİIN"
    assert to_latin("Иә") == "İä"


def test_placeholders_and_tags_untouched():
    assert to_latin("Сәлем, {name}! <g>{x}X</g>\\n") == "Sälem, {name}! <g>{x}X</g>\\n"


def test_arb_rewrite_keeps_structure_and_reports_growth():
    lines = [
        '{\n',
        '  "@@locale": "kk",\n',
        '  "@@comment": "COMMON",\n',
        '  "chat": "Чат",\n',
        '  "long": "Цирк, чат, юла",\n',
        '  "@long": {"description": "x"}\n',
        '}\n',
    ]
    out, grown = translit_kk.transliterate_lines(lines)
    data = json.loads("".join(out))
    assert data["@@locale"] == "kk"
    assert data["@@comment"] == "COMMON"
    assert data["chat"] == "Chat"
    assert data["long"] == "Tsirk, chat, iula"
    assert [g["key"] for g in grown] == ["long"]
