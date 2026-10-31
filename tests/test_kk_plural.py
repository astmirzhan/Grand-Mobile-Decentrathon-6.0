from locqa.lang.plural import is_unused_plural_key, plural_category


def test_plural_category_from_key():
    assert plural_category("timerPickerHourLabelFew") == "few"
    assert plural_category("selectedRowCountTitleOther") == "other"
    assert plural_category("closeButtonTooltip") is None


def test_russian_only_plural_forms_are_not_missing_in_kazakh():
    kk_keys = {"timerPickerHourLabelOne", "timerPickerHourLabelOther"}
    assert is_unused_plural_key("timerPickerHourLabelFew", kk_keys)
    assert is_unused_plural_key("timerPickerHourLabelMany", kk_keys)
    assert not is_unused_plural_key("timerPickerHourLabelOne", kk_keys)


def test_needs_a_sibling_form_in_the_target():
    # no other form of the same message in kk: it may be a real missing string
    assert not is_unused_plural_key("timerPickerHourLabelFew", set())
    assert not is_unused_plural_key("bestFriendsMany", {"somethingElseOther"})
