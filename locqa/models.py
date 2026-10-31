from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

Severity = Literal["high", "medium", "low"]

ISSUE_PRIORITY: list[str] = [
    "untranslated",
    "wrong_language",
    "same_as_source",
    "placeholder_mismatch",
    "plural_mismatch",
    "suffix_harmony",
    "orthography",
    "glossary_violation",
    "inconsistent_term",
    "length_overflow",
    "machine_translation_suspect",
]

DEFAULT_SEVERITY: dict[str, Severity] = {
    "untranslated": "high",
    "wrong_language": "high",
    "same_as_source": "high",
    "placeholder_mismatch": "high",
    "plural_mismatch": "high",
    "suffix_harmony": "high",
    "orthography": "medium",
    "glossary_violation": "medium",
    "inconsistent_term": "medium",
    "length_overflow": "medium",
    "machine_translation_suspect": "low",
}


def compute_severity(
    issue_type: str,
    key: str = "",
    section: str = "",
    description: str = "",
) -> Severity:
    if issue_type == "length_overflow":
        text = f"{key} {section} {description}".lower()
        if any(w in text for w in ("btn", "button", "кнопк", "cta")):
            return "high"
    return DEFAULT_SEVERITY.get(issue_type, "medium")


@dataclass
class Finding:
    key: str
    issue_type: str
    severity: str = ""
    source: str = ""
    target: str = ""
    evidence: str = ""
    suggestion: str | None = ""
    confidence: float = 1.0
    reviewed_by_human: bool = False
    fragment: str | None = None

    def __post_init__(self) -> None:
        if not self.severity:
            self.severity = compute_severity(self.issue_type, key=self.key)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("fragment", None)
        return {
            "key": d["key"],
            "issue_type": d["issue_type"],
            "severity": d["severity"],
            "source": d["source"],
            "target": d["target"],
            "evidence": d["evidence"],
            "suggestion": d["suggestion"] if d["suggestion"] is not None else "",
            "confidence": d["confidence"],
            "reviewed_by_human": d["reviewed_by_human"],
        }


@dataclass
class Context:
    ru: dict[str, str]
    kk: dict[str, str]
    en: dict[str, str] = field(default_factory=dict)
    uz: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    descriptions: dict[str, str] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    no_llm: bool = False

    @property
    def source(self) -> dict[str, str]:
        return self.ru

    @property
    def target(self) -> dict[str, str]:
        return self.kk


CheckFunc = Callable[[Context], list[Finding]]