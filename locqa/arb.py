from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class _ObjectPairs(list):
    """Distinguish JSON objects from arrays, including empty ones."""


@dataclass
class ParsedArb:
    values: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    descriptions: dict[str, str] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_pairs: list[tuple[str, Any]] = field(default_factory=list)


def _pairs_to_dict(obj: Any) -> Any:
    """Превращает вложенные списки пар от object_pairs_hook обратно в dict."""
    if isinstance(obj, _ObjectPairs):
        return {k: _pairs_to_dict(v) for k, v in obj}
    if isinstance(obj, list):
        return [_pairs_to_dict(item) for item in obj]
    return obj


def load_arb(path: str | Path) -> ParsedArb:
    """
    Читает .arb через object_pairs_hook=list, чтобы не потерять
    повторяющиеся @@comment и исходный порядок ключей.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8-sig") as f:
        pairs: list[tuple[str, Any]] = json.load(f, object_pairs_hook=_ObjectPairs)

    result = ParsedArb(raw_pairs=pairs)
    current_section = ""

    for k, v in pairs:
        if k == "@@comment" or k.startswith("@@comment"):
            current_section = str(v)
        elif k.startswith("@@"):
            continue
        elif k.startswith("@"):
            target_key = k[1:]
            meta_dict = _pairs_to_dict(v)
            if isinstance(meta_dict, dict):
                result.meta[target_key] = meta_dict
                desc = meta_dict.get("description")
                if isinstance(desc, str):
                    result.descriptions[target_key] = desc
        else:
            if isinstance(v, str):
                result.values[k] = v
            else:
                result.values[k] = "" if v is None else str(v)
            result.order.append(k)
            if current_section:
                result.sections[k] = current_section

    return result


@dataclass
class _Member:
    key: str
    raw: str
    value_start: int

    def replace(self, value: Any) -> None:
        self.raw = self.raw[:self.value_start] + json.dumps(value, ensure_ascii=False)


def _members(text: str) -> tuple[list[_Member], str]:
    """Parse complete top-level values, retaining whitespace and duplicate @@comment keys."""
    decoder = json.JSONDecoder()
    start = len(text) - len(text.lstrip())
    if start >= len(text) or text[start] != "{":
        raise ValueError("ARB must be a JSON object")
    members = []
    i = start + 1
    while True:
        raw_start = i
        while i < len(text) and text[i].isspace():
            i += 1
        if i < len(text) and text[i] == "}":
            return members, text[raw_start:i]
        key, key_end = decoder.raw_decode(text, i)
        if not isinstance(key, str):
            raise ValueError("ARB keys must be strings")
        i = key_end
        while text[i].isspace():
            i += 1
        if text[i] != ":":
            raise ValueError("Expected ':' after ARB key")
        i += 1
        while text[i].isspace():
            i += 1
        value_start = i
        _, i = decoder.raw_decode(text, i)
        members.append(_Member(key, text[raw_start:i], value_start - raw_start))
        raw_start = i
        while i < len(text) and text[i].isspace():
            i += 1
        if text[i] == "}":
            return members, text[raw_start:i]
        if text[i] != ",":
            raise ValueError("Expected ',' between ARB members")
        i += 1


def update_arb_file(
    target_path: str | Path,
    out_path: str | Path,
    updates: dict[str, str],
    ru_order: list[str] | None = None,
    review_meta: dict[str, dict[str, Any]] | None = None,
    fallback_meta: bool = False,
) -> None:
    """Update complete JSON values, preserving untouched text, metadata and sections.

    Compact ARB and multiline metadata are supported. The output is parsed before
    an atomic replace, so failed validation cannot truncate an existing result.
    """
    import os
    import tempfile

    text = Path(target_path).read_text(encoding="utf-8-sig")
    json.loads(text)  # reject malformed input before making changes
    members, tail = _members(text)
    for member in members:
        if member.key in updates:
            member.replace(updates[member.key])

    existing = {m.key for m in members}
    reference = ru_order or list(updates)
    missing = [k for k in reference if k in updates and k not in existing]
    missing += [k for k in updates if k not in existing and k not in missing]
    for key in missing:
        pos = len(members)
        if key in reference:
            for prev in reversed(reference[:reference.index(key)]):
                positions = [i for i, m in enumerate(members) if m.key == prev]
                if positions:
                    pos = positions[-1] + 1
                    while pos < len(members) and members[pos].key == "@" + prev:
                        pos += 1
                    break
            else:
                for following in reference[reference.index(key) + 1:]:
                    positions = [i for i, m in enumerate(members) if m.key == following]
                    if positions:
                        pos = positions[0]
                        break
        raw = "\n  " + json.dumps(key, ensure_ascii=False) + ": "
        members.insert(pos, _Member(key, raw + json.dumps(updates[key], ensure_ascii=False), len(raw)))

    for key, meta in (review_meta or {}).items():
        meta_key = ("@@x-reviewed-" if fallback_meta else "@") + key
        matches = [m for m in members if m.key == meta_key]
        if matches:
            for member in matches:
                member.replace(meta)
        else:
            pos = next((i + 1 for i, m in enumerate(members) if m.key == key), None)
            if pos is not None:
                raw = "\n  " + json.dumps(meta_key, ensure_ascii=False) + ": "
                members.insert(pos, _Member(meta_key, raw + json.dumps(meta, ensure_ascii=False), len(raw)))

    output = "{" + ",".join(m.raw for m in members) + (tail or "\n") + "}\n"
    json.loads(output)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent, delete=False) as f:
            temp = Path(f.name)
            f.write(output)
        os.replace(temp, out)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
