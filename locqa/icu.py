from __future__ import annotations

import re

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def check_balanced_braces(s: str) -> bool:
    """Проверяет баланс фигурных скобок счётчиком (с учётом экранирования апострофом)."""
    depth = 0
    in_quote = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            if in_quote:
                in_quote = False
            elif i + 1 < len(s) and s[i + 1] in "{}#":
                in_quote = True
        elif not in_quote:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return False
        i += 1
    return depth == 0


def _iter_brace_blocks(s: str) -> list[str]:
    """Возвращает содержимое верхнеуровневых блоков {...} через счётчик скобок."""
    blocks: list[str] = []
    depth = 0
    start = -1
    in_quote = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            if in_quote:
                in_quote = False
            elif i + 1 < len(s) and s[i + 1] in "{}#":
                in_quote = True
        elif not in_quote:
            if ch == "{":
                if depth == 0:
                    start = i + 1
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    blocks.append(s[start:i])
                    start = -1
        i += 1
    return blocks


def extract_placeholders(s: str) -> set[str]:
    """
    Извлекает множество имён плейсхолдеров ({name}, {count}) со вложенными скобками.
    """
    if not s:
        return set()
    names: set[str] = set()
    for content in _iter_brace_blocks(s):
        parts = content.split(",", 2)
        var_name = parts[0].strip()
        if _IDENT_RE.match(var_name):
            names.add(var_name)
        # Если это plural/select, рекурсивно извлекаем плейсхолдеры из вложенных веток
        if len(parts) == 3 and parts[1].strip() in ("plural", "select", "selectordinal"):
            for sub_block in _iter_brace_blocks(parts[2]):
                names.update(extract_placeholders(sub_block))
    return names


def _extract_plural_categories(body: str) -> dict[str, str]:
    """Parse ICU branches; reject duplicate selectors and unconsumed syntax."""
    categories: dict[str, str] = {}
    pos = 0
    offset = re.match(r"\s*offset:\s*\d+\s*", body)
    if offset:
        pos = offset.end()
    while pos < len(body):
        if not body[pos:].strip():
            break
        match = re.match(r"\s*(=?[\w.-]+)\s*\{", body[pos:])
        if not match:
            return {}
        key = match.group(1)
        if key in categories:
            return {}
        opening = pos + match.end() - 1
        depth, quoted, end = 1, False, opening + 1
        while end < len(body) and depth:
            ch = body[end]
            if ch == "'":
                if end + 1 < len(body) and body[end + 1] == "'":
                    end += 2
                    continue
                if quoted:
                    quoted = False
                elif end + 1 < len(body) and body[end + 1] in "{}#":
                    quoted = True
            elif not quoted:
                depth += (ch == "{") - (ch == "}")
            end += 1
        if depth:
            return {}
        categories[key] = body[opening + 1:end - 1]
        pos = end
    return categories


def has_icu_complex(s: str) -> bool:
    for content in _iter_brace_blocks(s):
        parts = content.split(",", 2)
        if len(parts) == 3 and parts[1].strip() in ("plural", "select", "selectordinal"):
            return True
    return False


def validate_plural(s: str, lang: str = "kk") -> list[str]:
    """
    Проверяет сбалансированность скобок и наличие обязательных CLDR-форм в plural/select.
    Ветка `other` обязательна; `one` необязательна (как в Flutter).
    """
    errors: list[str] = []
    if not check_balanced_braces(s):
        errors.append("Несбалансированные фигурные скобки '{' и '}'")
        return errors

    for content in _iter_brace_blocks(s):
        parts = content.split(",", 2)
        if len(parts) < 2:
            continue
        var_name = parts[0].strip()
        kind = parts[1].strip()
        if kind not in ("plural", "select", "selectordinal"):
            continue
        if len(parts) < 3 or not parts[2].strip():
            errors.append(f"В конструкции {kind} ({var_name}) отсутствует тело форм")
            continue

        categories = _extract_plural_categories(parts[2])
        if not categories:
            errors.append(f"Не удалось разобрать ветки {kind} для переменной '{var_name}'")
            continue

        if kind in ("plural", "selectordinal"):
            allowed = {"zero", "one", "two", "few", "many", "other"}
            invalid = [c for c in categories if c not in allowed and not re.fullmatch(r"=\d+", c)]
            if invalid:
                errors.append(f"Недопустимые ветки {kind}: {invalid}")
        if "other" not in categories:
            errors.append(f"В {kind} ({var_name}) отсутствует обязательная форма 'other'")

        # Рекурсивная проверка вложенных веток
        for cat_name, cat_body in categories.items():
            sub_errors = validate_plural(cat_body, lang=lang)
            for se in sub_errors:
                errors.append(f"В ветке '{cat_name}': {se}")

    return errors