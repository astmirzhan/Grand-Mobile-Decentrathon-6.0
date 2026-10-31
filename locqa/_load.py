"""Shared ARB loading adapter for review tools and auxiliary scripts."""
from __future__ import annotations

from pathlib import Path

from .glossary import load_glossary
from .models import Context


def read_arb(path: str | Path) -> tuple[dict[str, str], list[str], dict[str, str], dict[str, str]]:
    """Возвращает (значения, порядок ключей, ключ -> раздел, ключ -> description).

    Пары читаются списком, иначе повторяющиеся "@@comment" теряются.
    """
    from .arb import load_arb
    doc = load_arb(path)
    return doc.values, doc.order, doc.sections, doc.descriptions


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
