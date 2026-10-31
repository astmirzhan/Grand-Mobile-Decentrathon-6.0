"""Plural categories per language (CLDR) and Flutter's split plural keys.

Flutter's own localizations store plural forms as separate keys:
`timerPickerHourLabelOne / ...Few / ...Many / ...Other`. Russian needs one, few, many and
other; Kazakh only one and other. A `...Few` key that exists in ru but not in kk is therefore
not a missing translation.
"""
import re

# CLDR cardinal plural categories (https://cldr.unicode.org, plural rules)
CATEGORIES = {
    "kk": ("one", "other"),
    "uz": ("one", "other"),
    "en": ("one", "other"),
    "ru": ("one", "few", "many", "other"),
    "es": ("one", "many", "other"),
    "pt": ("one", "many", "other"),
}

_SUFFIX = re.compile(r"(Zero|One|Two|Few|Many|Other)$")


def plural_category(key: str) -> str | None:
    """Plural category encoded in a split plural key: 'timerPickerHourLabelFew' -> 'few'."""
    m = _SUFFIX.search(key)
    return m.group(1).lower() if m else None


def is_unused_plural_key(key: str, target_keys, locale: str = "kk") -> bool:
    """True for a split plural key whose category the target language does not have,
    when the target file has another form of the same message (so it is a plural group,
    not a word that happens to end in 'Other')."""
    category = plural_category(key)
    if category is None or category in CATEGORIES.get(locale, ("one", "other")):
        return False
    base = key[: -len(category)]
    return any(f"{base}{c.capitalize()}" in target_keys for c in CATEGORIES.get(locale, ("other",)))
