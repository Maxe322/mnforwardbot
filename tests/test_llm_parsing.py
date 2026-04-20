import pytest

from forwardbot.llm import (
    OpenAICompatibleProvider,
    _build_system_prompt,
    _build_user_prompt,
    _parse_headline_variants,
    _parse_rewrite_draft,
)
from forwardbot.models import IncomingPost, RewriteResult, RewriteValidationError
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


def test_parse_headline_variants_reads_json_object() -> None:
    variants = _parse_headline_variants('{"variants": ["Titel A", "Titel B", "Titel C"]}')

    assert variants == ["Titel A", "Titel B", "Titel C"]


def test_system_prompt_contains_title_and_approved_sections() -> None:
    prompt = _build_system_prompt(
        StyleContext(rules="rules", examples="examples", approved_examples="approved examples")
    )

    assert "vollständige, konkrete Headline" in prompt
    assert "Geheime Entscheidung" in prompt
    assert "Flaggen dürfen nur im title stehen" in prompt
    assert "echte Umlaute" in prompt
    assert "## Kanon-Stilbeispiele" in prompt
    assert "## Zuletzt vom Redakteur freigegebene Beispiele" in prompt


def test_user_prompt_includes_repair_feedback_and_modifier_when_present() -> None:
    prompt = _build_user_prompt(
        IncomingPost(sender_user_id=1, chat_id=1, source_text="hello"),
        max_output_chars=500,
        repair_feedback="Der erste Absatz wiederholt den title.",
        current_draft=RewriteResult(
            short_mode=False,
            title="Titel",
            paragraphs=("Absatz",),
            formatted_html="<b>Titel</b>\n\nAbsatz",
        ),
        modifier_text="Kürze den Entwurf.",
    )

    assert "Zusätzlicher Korrekturhinweis" in prompt
    assert "wiederholt den title" in prompt
    assert "Hier ist der bisherige Entwurf" in prompt
    assert "Kürze den Entwurf" in prompt


@pytest.mark.asyncio
async def test_provider_generate_headline_variants_uses_json_response() -> None:
    provider = OpenAICompatibleProvider(
        api_key="key",
        base_url="https://example.com/v1",
        model="model",
        disable_thinking=False,
        temperature=0.2,
        timeout_seconds=1,
    )

    async def fake_request_completion(payload):
        assert payload["messages"][1]["content"].startswith("Liefere NUR 3 alternative Titel-Vorschläge")
        return '{"variants": ["Titel 1", "Titel 2", "Titel 3"]}'

    provider._request_completion = fake_request_completion  # type: ignore[method-assign]
    try:
        variants = await provider.generate_headline_variants(
            IncomingPost(sender_user_id=1, chat_id=1, source_text="source"),
            RewriteResult(short_mode=False, title="Alt", paragraphs=("Absatz",), formatted_html="<b>Alt</b>"),
            StyleContext(rules="rules", examples="examples"),
        )
    finally:
        await provider.close()

    assert variants == ["Titel 1", "Titel 2", "Titel 3"]
