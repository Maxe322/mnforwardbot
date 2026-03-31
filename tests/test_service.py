from forwardbot.models import IncomingPost, RewriteDraft
from forwardbot.service import _normalize_structure


def test_long_source_short_draft_becomes_long_form() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Sentence one. Sentence two with more context. Sentence three continues the report. "
            "Sentence four closes the summary."
        ),
    )
    draft = RewriteDraft(
        short_mode=True,
        title=None,
        paragraphs=(
            "🇺🇸🇮🇷 Trump will Krieg gegen Iran auch bei geschlossener Straße von Hormus beenden. "
            "Das Weiße Haus fürchtet einen längeren Militäreinsatz. "
            "Die USA wollen stattdessen Irans Schlagkraft schwächen. "
            "Europa und Golfstaaten sollen später mehr Last übernehmen.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.short_mode is False
    assert normalized.title is not None
    assert len(normalized.paragraphs) >= 2


def test_long_single_paragraph_gets_split() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text="Sentence one. Sentence two. Sentence three. Sentence four.",
    )
    draft = RewriteDraft(
        short_mode=False,
        title="🇺🇸🇮🇷 Lageupdate",
        paragraphs=(
            "Satz eins. Satz zwei mit zusätzlichem Kontext. Satz drei mit weiterem Kontext. "
            "Satz vier schließt die Meldung ab.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.short_mode is False
    assert normalized.title == "🇺🇸🇮🇷 Lageupdate"
    assert len(normalized.paragraphs) >= 2
