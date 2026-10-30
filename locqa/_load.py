"""Минимальная загрузка ARB и глоссария для LLM-части.

Нужна, чтобы LLM-модули запускались до готовности arb.py (Человек 1).
После мёржа build_context можно заменить на загрузчик из arb.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from .glossary import load_glossary
from .models import Context


def read_arb(path: str | Path) -> tuple[dict[str, str], list[str], dict[str, str], dict[str, str]]:
    """Возвращает (значения, порядок ключей, ключ -> раздел, ключ -> description).

    Пары читаются списком, иначе повторяющиеся "@@comment" теряются.
    """
    with open(path, encoding="utf-8") as f:
        pairs = json.load(f, object_pairs_hook=lambda p: p)
    values: dict[str, str] = {}
    order: list[str] = []
    sections: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    section = ""
    for k, v in pairs:
        if k == "@@comment":
            section = v
        elif k.startswith("@"):
            if isinstance(v, list):
                desc = dict(v).get("description")
                if isinstance(desc, str):
                    descriptions[k[1:]] = desc
        elif isinstance(v, str):
            if k not in values:
                order.append(k)
            values[k] = v
            sections[k] = section
    return values, order, sections, descriptions


def read_glossary(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return load_glossary(path)


def build_context(source, target, en=None, uz=None, glossary=None) -> Context:
    ru, order, sections, descriptions = read_arb(source)
    kk = read_arb(target)[0]
    return Context(
        ru=ru,
        kk=kk,
        en=read_arb(en)[0] if en else {},
        uz=read_arb(uz)[0] if uz else {},
        order=order,
        descriptions=descriptions,
        sections=sections,
        glossary=read_glossary(glossary),
    )
