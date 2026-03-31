from forwardbot.models import RewriteDraft
from forwardbot.rendering import plain_text_length, render_rewrite


def test_short_mode_renders_single_plain_block() -> None:
    draft = RewriteDraft(
        short_mode=True,
        title=None,
        paragraphs=("Kurzmeldung mit zwei Saetzen.",),
    )

    result = render_rewrite(draft, max_plain_text_chars=200)

    assert result.short_mode is True
    assert result.title is None
    assert result.formatted_html == "Kurzmeldung mit zwei Saetzen."


def test_long_form_renders_bold_title_and_paragraphs() -> None:
    draft = RewriteDraft(
        short_mode=False,
        title="🇺🇦🇷🇺⚡️ Lageupdate",
        paragraphs=("Erster Absatz.", "Zweiter Absatz."),
    )

    result = render_rewrite(draft, max_plain_text_chars=300)

    assert result.short_mode is False
    assert result.formatted_html.startswith("<b>🇺🇦🇷🇺⚡️ Lageupdate</b>")
    assert "Erster Absatz." in result.formatted_html
    assert "Zweiter Absatz." in result.formatted_html


def test_rendering_drops_footer_lines_and_fits_limit() -> None:
    draft = RewriteDraft(
        short_mode=False,
        title="🇩🇪🇺🇦 Titel",
        paragraphs=(
            "A" * 120,
            "#Ukraine",
            "Abonniere hier: @MilitaerNews",
        ),
    )

    result = render_rewrite(draft, max_plain_text_chars=70)

    assert plain_text_length(result.formatted_html) <= 70
    assert "#Ukraine" not in result.formatted_html
    assert "Abonniere hier" not in result.formatted_html

