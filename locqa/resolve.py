from __future__ import annotations

from collections import defaultdict

from locqa.models import ISSUE_PRIORITY, Finding

_PRIORITY_RANK = {name: idx for idx, name in enumerate(ISSUE_PRIORITY)}


def _rank(finding: Finding) -> int:
    return _PRIORITY_RANK.get(finding.issue_type, len(ISSUE_PRIORITY))


def resolve_findings(findings: list[Finding], key_order: list[str] | None = None) -> list[Finding]:
    """
    Группирует находки по key.
    Оставляет старшую по приоритету.
    Вторую оставляет только тогда, когда она относится к другому фрагменту строки.
    """
    by_key: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_key[f.key].append(f)

    ordered_keys = list(by_key.keys())
    if key_order:
        order_map = {k: i for i, k in enumerate(key_order)}
        ordered_keys.sort(key=lambda k: order_map.get(k, 10**9))

    resolved: list[Finding] = []

    for key in ordered_keys:
        group = sorted(by_key[key], key=_rank)
        primary = group[0]
        resolved.append(primary)

        # Если строка вообще не переведена, на другом языке или полностью совпадает с ru —
        # мелкие ошибки внутри неё не имеют смысла
        if primary.issue_type in ("untranslated", "wrong_language", "same_as_source"):
            continue

        seen_fragments = {primary.fragment}
        for candidate in group[1:]:
            if candidate.issue_type == primary.issue_type and candidate.fragment == primary.fragment:
                continue
            # Вторую оставляем только если явно указан другой фрагмент строки
            if candidate.fragment is not None and candidate.fragment not in seen_fragments:
                resolved.append(candidate)
                seen_fragments.add(candidate.fragment)

    return resolved