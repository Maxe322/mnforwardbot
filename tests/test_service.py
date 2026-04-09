from forwardbot.models import IncomingPost, RewriteDraft
from forwardbot.service import _build_headline, _normalize_structure


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
            "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7 Trump will Krieg gegen Iran auch bei geschlossener Strasse von Hormus beenden. "
            "Das Weisse Haus fuerchtet einen laengeren Militaereinsatz. "
            "Die USA wollen stattdessen Irans Schlagkraft schwaechen. "
            "Europa und Golfstaaten sollen spaeter mehr Last uebernehmen.",
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
        title="\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7 Lageupdate",
        paragraphs=(
            "Satz eins. Satz zwei mit zusaetzlichem Kontext. Satz drei mit weiterem Kontext. "
            "Satz vier schliesst die Meldung ab.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.short_mode is False
    assert normalized.title == "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7 Lageupdate"
    assert len(normalized.paragraphs) >= 2


def test_build_headline_avoids_random_ellipsis_and_keeps_flags() -> None:
    headline = _build_headline(
        "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7\U0001F1F4\U0001F1F2 "
        "Iran und Oman erheben laut AP Mautgebuehren fuer alle Schiffe, "
        "die waehrend der zweiwoechigen Waffenruhe durch die Strasse von Hormus fahren."
    )

    assert headline.startswith("\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7\U0001F1F4\U0001F1F2 ")
    assert "..." not in headline
    assert "\u2026" not in headline
    assert len(headline) <= 100


def test_bad_generated_title_gets_repaired() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Iran und Oman erheben laut AP Mautgebuehren fuer alle Schiffe waehrend der Waffenruhe. "
            "Damit zementiert Iran die de-facto-Kontrolle ueber die Meerenge."
        ),
    )
    draft = RewriteDraft(
        short_mode=False,
        title=(
            "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F7\U0001F1F4\U0001F1F2 Iran und Oman erheben laut AP "
            "Mautgebuehren fuer alle Schiffe, die waehrend der zweiwoechigen Waffenruhe durch die..."
        ),
        paragraphs=(
            "Damit zementiert Iran die de-facto-Kontrolle ueber die Meerenge und etabliert einen neuen rechtlichen Rahmen.",
            "Die Durchfahrt soll damit faktisch neu geregelt werden.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.title is not None
    assert "..." not in normalized.title
    assert "\u2026" not in normalized.title
    assert len(normalized.title) <= 100


def test_duplicate_title_prefix_is_removed_from_first_paragraph() -> None:
    post = IncomingPost(
        sender_user_id=1,
        chat_id=1,
        source_text=(
            "Trump soll Netanyahu gruennes Licht fuer weitere Angriffe auf den Libanon gegeben haben. "
            "Laut Journalist Barak Ravid soll Trump gesagt haben, Israel koenne in Libanon weitermachen."
        ),
    )
    draft = RewriteDraft(
        short_mode=False,
        title="\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F1\U0001F1F1\U0001F1E7 Trump soll Netanyahu gruennes Licht fuer weitere Angriffe auf den Libanon gegeben haben",
        paragraphs=(
            "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F1\U0001F1F1\U0001F1E7 Trump soll Netanyahu gruennes Licht fuer weitere Angriffe auf den Libanon gegeben haben - direkt nach Verkuendung des eigenen Waffenstillstands.",
            "Laut Journalist Barak Ravid soll Trump gesagt haben: Israel koenne in Libanon weitermachen.",
        ),
    )

    normalized = _normalize_structure(post, draft)

    assert normalized.title == draft.title
    assert normalized.paragraphs[0].startswith("direkt nach Verkuendung")
    assert "\U0001F1FA\U0001F1F8\U0001F1EE\U0001F1F1\U0001F1F1\U0001F1E7" not in normalized.paragraphs[0]
