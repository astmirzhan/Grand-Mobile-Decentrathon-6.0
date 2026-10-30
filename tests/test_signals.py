from conftest import make_ctx

from locqa.checks import signals


def ctx_with_uz(rows, uz):
    ctx = make_ctx(rows)
    ctx.uz = uz
    return ctx


def test_brand_replaced_gets_fix():
    ctx = ctx_with_uz({"apple": ("Apple успешно привязан", "Google сәтті байланысқан")},
                      {"apple": "Apple muvaffaqiyatli ulandi"})
    [f] = signals.brand_mismatch(ctx)
    assert f.confidence == 0.95 and f.suggestion == "Apple сәтті байланысқан"


def test_brand_translit_and_common_words_are_ok():
    ctx = ctx_with_uz({
        "tesla": ("Завод Tesla", "Тесла зауыты"),  # транслитерация
        "gas": ("Обменяйте на Gasoline", "Бензинге ауыстырыңыз"),  # uz тоже перевёл слово
        "mail": ("Укажите email", "Электрондық поштаны көрсетіңіз"),  # с маленькой буквы — не имя
    }, {"tesla": "Tesla zavodi", "gas": "Benzinga almashtiring", "mail": "email kiriting"})
    assert signals.brand_mismatch(ctx) == []


def test_brand_dropped():
    ctx = ctx_with_uz({"twix": ("Фабрика Twix", "Ыстық зат фабрикасы")}, {"twix": "Twix fabrikasi"})
    [f] = signals.brand_mismatch(ctx)
    assert "Twix" in f.evidence and f.confidence == 0.7


def test_numbers():
    ctx = make_ctx({
        "bad": ("от 1 до 70 символов", "3-тен 90 таңбаға дейін"),
        "sep": ("Цена 50 000 000", "Бағасы 50.000.000"),  # разделители тысяч
        "word": ("не меньше трёх символов", "кемінде 3 таңба"),  # число словом
        "frac": ("1/4 финала", "ширек финал"),  # дробь переводится словом
        "url": ("https://x.gg/ru/1474", "https://x.gg/en/1475"),
    })
    [f] = signals.number_mismatch(ctx)
    assert f.key == "bad" and f.confidence == 0.85
