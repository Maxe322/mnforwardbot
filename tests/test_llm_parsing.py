import pytest

from forwardbot.llm import _build_system_prompt, _parse_rewrite_draft
from forwardbot.models import RewriteValidationError
from forwardbot.style_loader import StyleContext


def test_parse_llm_json_from_code_fence() -> None:
    content = """```json
    {"short_mode": false, "title": "🇮🇱🇵🇸⚡️ Titel", "paragraphs": ["Absatz 1", "Absatz 2"]}
    ```"""

    draft = _parse_rewrite_draft(content)

    assert draft.short_mode is False
    assert draft.title == "🇮🇱🇵🇸⚡️ Titel"
    assert draft.paragraphs == ("Absatz 1", "Absatz 2")


def test_parse_llm_short_mode_requires_text() -> None:
    with pytest.raises(RewriteValidationError):
        _parse_rewrite_draft('{"short_mode": true, "title": null, "paragraphs": []}')


def test_system_prompt_contains_title_and_dedup_rules() -> None:
    prompt = _build_system_prompt(StyleContext(rules="rules", examples="examples"))

    assert "konkrete Headline" in prompt
    assert "Geheime Entscheidung" in prompt
    assert "Flaggen duerfen nur im title stehen" in prompt
