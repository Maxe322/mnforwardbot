from forwardbot.models import IncomingPost, RewriteDraft
from forwardbot.service import (
    _build_headline,
    _collect_quality_issues,
    _normalize_structure,
    _title_matches_paragraph,
)


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
    assert normalized.title is not None
    assert normalized.title != "🇺🇸🇮🇷 Lageupdate"
    assert len(normalized.paragraphs) >= 2


def test_build_headline_avoids_random_ellipsis_and_keeps_flags() -> None:
    headline = _build_headline(
        "🇺🇸🇮🇷🇴🇲 Iran und Oman erheben laut AP Mautgebühren für alle Schiffe, "
        "die während der zweiwöchigen Waffenruhe durch die Straße von Hormus fahren."
    )

    assert headline.startswith("🇺🇸🇮🇷🇴🇲 ")
    assert "..." not in headline
    assert "…" not in headline
    assert len(headline) <= 124


def test_dedupe_removes_title_with_flag_prefix() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben. "
            "Laut Journalist Barak Ravid soll Trump gesagt haben, Israel könne im Libanon weitermachen."
        ),
    )
    draft = RewriteDraft(
        short_mode=False,
        title="🇺🇸🇮🇱🇱🇧 Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben",
        paragraphs=(
            "🇺🇸🇮🇱🇱🇧 Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben – "
            "direkt nach Verkündung des eigenen Waffenstillstands.",
            "Laut Journalist Barak Ravid soll Trump gesagt haben: Israel könne im Libanon weitermachen.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.title == draft.title
    assert normalized.paragraphs[0].startswith("direkt nach Verkündung")
    assert "🇺🇸🇮🇱🇱🇧" not in normalized.paragraphs[0]


def test_dedupe_removes_title_substring_match() -> None:
    assert _title_matches_paragraph(
        "🇮🇱🇵🇸 Israels Kabinett genehmigt 34 neue Siedlungen im Westjordanland",
        "Israels Kabinett genehmigt 34 neue Siedlungen im Westjordanland und hält die Entscheidung zunächst geheim.",
    )


def test_repair_detects_truncated_title() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Iran und Oman erheben laut AP Mautgebühren für alle Schiffe während der Waffenruhe. "
            "Damit zementiert Iran die de-facto-Kontrolle über die Meerenge."
        ),
    )
    draft = RewriteDraft(
        short_mode=False,
        title="🇺🇸🇮🇷🇴🇲 Iran und Oman erheben laut AP Mautgebühren für alle Schiffe, die während",
        paragraphs=(
            "Damit zementiert Iran die de-facto-Kontrolle über die Meerenge und etabliert einen neuen rechtlichen Rahmen.",
            "Die Durchfahrt soll damit faktisch neu geregelt werden.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.title is not None
    assert normalized.title != draft.title
    assert not normalized.title.endswith("während")
    assert "…" not in normalized.title


def test_validator_flags_ascii_transliteration() -> None:
    draft = RewriteDraft(
        short_mode=False,
        title="🇬🇧 Großbritannien veröffentlicht neue Zahlen",
        paragraphs=("Die Regierung hat veroeffentlicht, dass weitere Bestaende geprüft werden.",),
    )

    issues = _collect_quality_issues(draft)

    assert any("Umlaute" in issue for issue in issues)


def test_integration_keeps_only_one_title_for_trump_lebanon_example() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben. "
            "Laut Journalist Barak Ravid soll Trump gesagt haben: "
            "\"You can continue on doing what you're doing in Lebanon.\""
        ),
    )
    draft = RewriteDraft(
        short_mode=False,
        title="🇺🇸🇮🇱🇱🇧 Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben",
        paragraphs=(
            "🇺🇸🇮🇱🇱🇧 Trump soll Netanyahu grünes Licht für weitere Angriffe auf den Libanon gegeben haben",
            "Laut Journalist Barak Ravid soll Trump gesagt haben: „You can continue on doing what you're doing in Lebanon.“",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.title == draft.title
    assert normalized.paragraphs[0].startswith("Laut Journalist Barak Ravid")
    assert len(normalized.paragraphs) == 1
