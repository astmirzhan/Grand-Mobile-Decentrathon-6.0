from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    if isinstance(obj, list):
        if all(isinstance(item, tuple) and len(item) == 2 for item in obj):
            return {k: _pairs_to_dict(v) for k, v in obj}
        return [_pairs_to_dict(item) for item in obj]
    return obj


def load_arb(path: str | Path) -> ParsedArb:
    """
    Читает .arb через object_pairs_hook=list, чтобы не потерять
    повторяющиеся @@comment и исходный порядок ключей.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        pairs: list[tuple[str, Any]] = json.load(f, object_pairs_hook=list)

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


_KEY_LINE_RE = re.compile(r'^(\s*)"((?:\\.|[^"\\])*)"(\s*:\s*)(.*?)(\s*,?\s*)$')


def update_arb_file(
    target_path: str | Path,
    out_path: str | Path,
    updates: dict[str, str],
    ru_order: list[str] | None = None,
    review_meta: dict[str, dict[str, Any]] | None = None,
    fallback_meta: bool = False,
) -> None:
    """
    Построчно обновляет значения в ARB-файле, не ломая @@comment, отступы и порядок.
    Отсутствующие ключи вставляет в то же место, где они стоят в ru_order.
    """
    target_p = Path(target_path)
    out_p = Path(out_path)
    lines = target_p.read_text(encoding="utf-8").splitlines()

    review_meta = review_meta or {}
    existing_keys: set[str] = set()
    key_line_idx: dict[str, int] = {}

    for i, line in enumerate(lines):
        m = _KEY_LINE_RE.match(line)
        if not m:
            continue
        indent, raw_key, sep, val_part, trailing = m.groups()
        key = json.loads(f'"{raw_key}"')
        if not key.startswith("@"):
            existing_keys.add(key)
            key_line_idx[key] = i
            if key in updates:
                new_val_json = json.dumps(updates[key], ensure_ascii=False)
                has_comma = trailing.strip().startswith(",") or val_part.rstrip().endswith(",")
                comma_str = "," if (has_comma or i < len(lines) - 2) else ""
                lines[i] = f'{indent}"{raw_key}"{sep}{new_val_json}{comma_str}'

    missing_keys = [k for k in updates if k not in existing_keys]
    if missing_keys:
        order_ref = ru_order or list(updates.keys())
        for mk in missing_keys:
            new_val_json = json.dumps(updates[mk], ensure_ascii=False)
            new_line = f'  "{mk}": {new_val_json},'
            insert_pos = None

            if mk in order_ref:
                idx_in_ru = order_ref.index(mk)
                for prev_k in reversed(order_ref[:idx_in_ru]):
                    if prev_k in key_line_idx:
                        insert_pos = key_line_idx[prev_k] + 1
                        while insert_pos < len(lines) and re.match(r'^\s*"@', lines[insert_pos]):
                            insert_pos += 1
                        break

            if insert_pos is None:
                insert_pos = len(lines) - 1
                while insert_pos > 0 and not lines[insert_pos].strip().startswith("}"):
                    insert_pos -= 1

            prev_idx = insert_pos - 1
            while prev_idx >= 0 and not lines[prev_idx].strip():
                prev_idx -= 1
            if prev_idx >= 0 and not lines[prev_idx].rstrip().endswith(("{", ",")):
                lines[prev_idx] = lines[prev_idx].rstrip() + ","

            lines.insert(insert_pos, new_line)
            for k_idx in key_line_idx:
                if key_line_idx[k_idx] >= insert_pos:
                    key_line_idx[k_idx] += 1
            key_line_idx[mk] = insert_pos
            existing_keys.add(mk)

    for rk, meta_dict in review_meta.items():
        if rk not in key_line_idx:
            continue
        pos = key_line_idx[rk]
        if not lines[pos].rstrip().endswith(","):
            lines[pos] = lines[pos].rstrip() + ","

        if fallback_meta:
            meta_line = f'  "@@x-reviewed-{rk}": {json.dumps(meta_dict, ensure_ascii=False)},'
        else:
            meta_line = f'  "@{rk}": {json.dumps(meta_dict, ensure_ascii=False)},'

        if pos + 1 < len(lines) and re.match(rf'^\s*"@{re.escape(rk)}"\s*:', lines[pos + 1]):
            lines[pos + 1] = meta_line
        else:
            lines.insert(pos + 1, meta_line)
            for k_idx in key_line_idx:
                if key_line_idx[k_idx] > pos:
                    key_line_idx[k_idx] += 1

    close_idx = len(lines) - 1
    while close_idx > 0 and not lines[close_idx].strip().startswith("}"):
        close_idx -= 1
    last_item_idx = close_idx - 1
    while last_item_idx > 0 and not lines[last_item_idx].strip():
        last_item_idx -= 1
    if last_item_idx > 0 and lines[last_item_idx].rstrip().endswith(","):
        lines[last_item_idx] = lines[last_item_idx].rstrip()[:-1]

    out_p.write_text("\n".join(lines) + "\n", encoding="utf-8")