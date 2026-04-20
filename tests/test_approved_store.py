from datetime import datetime, timezone

from forwardbot.approved_store import ApprovedExample, ApprovedStore


def _example(title: str) -> ApprovedExample:
    return ApprovedExample(
        title=title,
        paragraphs=["Absatz 1", "Absatz 2"],
        source_hint="Quelle",
        approved_at=datetime.now(timezone.utc),
    )


def test_add_and_load_roundtrip(tmp_path) -> None:
    store = ApprovedStore(tmp_path / "approved.jsonl")
    store.add(_example("Titel A"))

    loaded = store.load_all()

    assert len(loaded) == 1
    assert loaded[0].title == "Titel A"


def test_rotation_drops_oldest(tmp_path) -> None:
    store = ApprovedStore(tmp_path / "approved.jsonl", max_examples=3)
    for index in range(5):
        store.add(_example(f"Titel {index}"))

    loaded = store.load_all()

    assert [item.title for item in loaded] == ["Titel 2", "Titel 3", "Titel 4"]


def test_render_for_prompt_format(tmp_path) -> None:
    store = ApprovedStore(tmp_path / "approved.jsonl")
    store.add(_example("Titel A"))

    rendered = store.render_for_prompt()

    assert "### Beispiel" in rendered
    assert "**Titel**: Titel A" in rendered
    assert "**Quelle**: Quelle" in rendered


def test_empty_store_renders_empty_string(tmp_path) -> None:
    store = ApprovedStore(tmp_path / "approved.jsonl")

    assert store.render_for_prompt() == ""
