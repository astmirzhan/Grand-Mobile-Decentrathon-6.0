"""Finding contract used by language checks.

Uses the shared locqa.models.Finding when available; the fallback mirrors its fields
so language checks can be developed and tested before the core package lands.
"""
from dataclasses import dataclass

try:
    from locqa.models import Finding  # noqa: F401
except ImportError:  # pragma: no cover - exercised only before models.py exists
    @dataclass
    class Finding:
        key: str
        issue_type: str
        severity: str
        source: str
        target: str
        evidence: str
        suggestion: str | None
        confidence: float
        reviewed_by_human: bool = False
