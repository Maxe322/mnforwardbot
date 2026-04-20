from forwardbot.keyboards import build_draft_keyboard, build_headline_picker, parse_callback


def test_callback_data_stays_under_limit_for_all_actions() -> None:
    markup = build_draft_keyboard("a7Bx9k2Q")

    for row in markup.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) < 64

    picker = build_headline_picker("a7Bx9k2Q", ["Titel 1", "Titel 2", "Titel 3"])
    for row in picker.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) < 64


def test_parse_callback_roundtrip() -> None:
    assert parse_callback("d:sh:a7Bx9k2Q") == ("sh", "a7Bx9k2Q", None)
    assert parse_callback("d:nhP:a7Bx9k2Q:2") == ("nhP", "a7Bx9k2Q", "2")
