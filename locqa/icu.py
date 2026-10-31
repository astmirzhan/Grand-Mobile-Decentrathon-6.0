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
            in_quote = not in_quote
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
            in_quote = not in_quote
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
    """Парсит ветки вида `one {...} other {...}` внутри тела plural/select."""
    categories: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        key_start = i
        while i < n and not body[i].isspace() and body[i] != "{":
            i += 1
        cat_key = body[key_start:i].strip()
        while i < n and body[i].isspace():
            i += 1
        if i >= n or body[i] != "{":
            break
        depth = 0
        block_start = i + 1
        while i < n:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth == 0:
                    categories[cat_key] = body[block_start:i]
                    i += 1
                    break
            i += 1
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
    Для kk требуются формы `one` и `other`.
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

        if "other" not in categories:
            errors.append(f"В {kind} ({var_name}) отсутствует обязательная форма 'other'")

        if kind == "plural" and lang == "kk":
            if "one" not in categories:
                errors.append(
                    f"Для казахского языка (kk) по CLDR в plural ({var_name}) нужна форма 'one' и 'other' (найдены: { sorted(categories.keys()) })"
                )

        # Рекурсивная проверка вложенных веток
        for cat_name, cat_body in categories.items():
            sub_errors = validate_plural(cat_body, lang=lang)
            for se in sub_errors:
                errors.append(f"В ветке '{cat_name}': {se}")

    return errors