"""Общий контракт: любая проверка получает Context и возвращает list[Finding].

Файл повторяет схему из документа архитектуры (зона Человека 1).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    key: str
    issue_type: str  # один из 11 типов ТЗ
    severity: str  # high | medium | low
    source: str  # текст ru
    target: str  # текст kk
    evidence: str  # почему это ошибка
    suggestion: str | None
    confidence: float  # 0..1
    reviewed_by_human: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    ru: dict[str, str]
    kk: dict[str, str]
    en: dict[str, str] = field(default_factory=dict)
    uz: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # порядок ключей в ru
    descriptions: dict[str, str] = field(default_factory=dict)  # из @key
    sections: dict[str, str] = field(default_factory=dict)  # ключ -> раздел @@comment
    glossary: list[dict] = field(default_factory=list)
