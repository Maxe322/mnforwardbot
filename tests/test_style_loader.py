from datetime import datetime, timezone

from forwardbot.approved_store import ApprovedExample, ApprovedStore
from forwardbot.style_loader import StyleRepository


def test_system_prompt_includes_approved_section_when_nonempty(tmp_path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "style_rules.md").write_text("rules", encoding="utf-8")
    (prompts_dir / "style_examples.md").write_text("examples", encoding="utf-8")
    store = ApprovedStore(tmp_path / "data" / "approved.jsonl")
    store.add(
        ApprovedExample(
            title="Titel",
            paragraphs=["Absatz"],
            source_hint="Quelle",
            approved_at=datetime.now(timezone.utc),
        )
    )

    repository = StyleRepository(
        prompts_dir / "style_rules.md",
        prompts_dir / "style_examples.md",
        approved_store=store,
    )
    context = repository.load()

    assert "### Beispiel" in context.approved_examples
    assert "Titel" in context.approved_examples


def test_system_prompt_omits_section_when_empty(tmp_path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "style_rules.md").write_text("rules", encoding="utf-8")
    (prompts_dir / "style_examples.md").write_text("examples", encoding="utf-8")
    store = ApprovedStore(tmp_path / "data" / "approved.jsonl")

    repository = StyleRepository(
        prompts_dir / "style_rules.md",
        prompts_dir / "style_examples.md",
        approved_store=store,
    )
    context = repository.load()

    assert context.approved_examples == ""
