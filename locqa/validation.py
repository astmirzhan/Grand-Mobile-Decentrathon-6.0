"""Shared structural contract for suggestions, review import, fixes and release checks."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .arb import load_arb
from .icu import _iter_brace_blocks, extract_placeholders, has_icu_complex, validate_plural

PRINTF = re.compile(r"%(?:\d+\$)?[-+0 #]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[sdif] ", re.X)
TAGS = re.compile(r"</?[A-Za-z][^<>]*>")
SIMPLE = re.compile(r"\{([A-Za-z_]\w*)\}")


def _complex_arguments(text: str) -> set[tuple[str, str]]:
    arguments = set()
    for content in _iter_brace_blocks(text):
        parts = content.split(',', 2)
        if len(parts) == 3 and parts[1].strip() in {'plural', 'select', 'selectordinal'}:
            arguments.add((parts[0].strip(), parts[1].strip()))
            for branch in _iter_brace_blocks(parts[2]):
                arguments.update(_complex_arguments(branch))
    return arguments


def validate_text(source: str, target: str) -> list[str]:
    errors = validate_plural(target)
    if not _complex_arguments(source) <= _complex_arguments(target):
        errors.append("тип ICU-аргумента утрачен или заменён")
    if extract_placeholders(source) != extract_placeholders(target):
        errors.append("плейсхолдеры не совпадают с ru")
    elif not has_icu_complex(source) and not has_icu_complex(target):
        if Counter(SIMPLE.findall(source)) != Counter(SIMPLE.findall(target)):
            errors.append("число вхождений плейсхолдеров не совпадает с ru")
    if Counter(PRINTF.findall(source.replace('%%', ''))) != Counter(PRINTF.findall(target.replace('%%', ''))):
        errors.append("printf-параметры не совпадают с ru")
    if Counter(TAGS.findall(source)) != Counter(TAGS.findall(target)):
        errors.append("теги разметки не совпадают с ru")
    return errors


def validate_files(source: str | Path, target: str | Path, original: str | Path | None = None) -> dict:
    ru, kk = load_arb(source), load_arb(target)
    issues = []
    warnings = []
    for doc, label in ((ru, 'source'), (kk, 'target')):
        duplicates = Counter(k for k, _ in doc.raw_pairs if not k.startswith('@@'))
        warnings += [{'key': k, 'warning': f'{label}: duplicate resource/metadata key; effective last value used'}
                   for k, count in duplicates.items() if count > 1]
    for key, text in ru.values.items():
        if key not in kk.values:
            issues.append({'key': key, 'error': 'missing target key'})
        else:
            issues += [{'key': key, 'error': error} for error in validate_text(text, kk.values[key])]
    changed = []
    human = 0
    if original:
        before = load_arb(original)
        changed = [k for k, value in kk.values.items() if before.values.get(k) != value]
        for key in changed:
            meta = kk.meta.get(key, {})
            if not isinstance(meta.get('x-reviewed'), bool) or not meta.get('x-reviewer'):
                issues.append({'key': key, 'error': 'changed text needs explicit boolean x-reviewed and x-reviewer'})
            human += meta.get('x-reviewed') is True
    return {'valid': not issues, 'source_keys': len(ru.values), 'target_keys': len(kk.values),
            'changed': len(changed), 'human_reviewed_changes': human,
            'unreviewed_changes': len(changed) - human, 'issues': issues, 'warnings': warnings}
