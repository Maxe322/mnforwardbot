from forwardbot.models import RewriteDraft
from forwardbot.validator import extract_entities, validate_consistency


def test_extract_finds_proper_nouns() -> None:
    entities = extract_entities(
        "Trump sprach mit Hisbollah-Kommandeuren in Kiryat Shmona. Danach verließ Trump das Gebiet."
    )

    assert "Trump" in entities.proper_nouns
    assert "Hisbollah-Kommandeuren" in entities.proper_nouns
    assert "Kiryat Shmona" in entities.proper_nouns


def test_extract_finds_numbers_with_units() -> None:
    entities = extract_entities("Es wurden 17 Systeme, 10 Fahrzeuge und 130-mm-Munition gemeldet.")

    assert "17" in entities.numbers
    assert "10" in entities.numbers
    assert "130-mm" in entities.numbers


def test_validate_detects_missing_number() -> None:
    missing = validate_consistency(
        "Russland setzte 17 Drohnen ein.",
        RewriteDraft(short_mode=False, title="🇷🇺 Russland setzt Drohnen ein", paragraphs=("Die Angriffe dauern an.",)),
    )

    assert "17" in missing


def test_validate_fuzzy_matches_partial_names() -> None:
    missing = validate_consistency(
        "Die Hisbollah griff erneut an.",
        RewriteDraft(
            short_mode=False,
            title="🇱🇧 Hisbollah-Miliz greift erneut an",
            paragraphs=("Die Lage bleibt angespannt.",),
        ),
    )

    assert "Hisbollah" not in missing


def test_validate_ignores_common_stopwords() -> None:
    missing = validate_consistency(
        "Die Lage bleibt unklar.",
        RewriteDraft(short_mode=True, title=None, paragraphs=("Die Lage bleibt unklar.",)),
    )

    assert missing == []


def test_validate_detects_missing_abinsk_fixture_like_case() -> None:
    missing = validate_consistency(
        'Ukrainische Quellen melden einen Angriff auf ABINSK. Dabei sollen 10 Drohnen eingesetzt worden sein. "ABINSK" wurde als Ziel genannt.',
        RewriteDraft(
            short_mode=False,
            title="🇺🇦🇷🇺 Angriff auf russischen Standort gemeldet",
            paragraphs=("Ukrainische Quellen berichten von einem Angriff. Zehn Drohnen sollen eingesetzt worden sein.",),
        ),
    )

    assert "ABINSK" in missing
