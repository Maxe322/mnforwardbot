from pathlib import Path

import pytest

from forwardbot.config import SettingsError, load_settings


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "ALLOWED_USER_IDS",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_DISABLE_THINKING",
        "LLM_TEMPERATURE",
        "LLM_TIMEOUT_SECONDS",
        "LOG_LEVEL",
        "ALBUM_COLLECT_WINDOW_SECONDS",
        "TELEGRAM_CAPTION_LIMIT",
        "TELEGRAM_MESSAGE_LIMIT",
        "STYLE_RULES_PATH",
        "STYLE_EXAMPLES_PATH",
        "DRAFT_CACHE_TTL_SECONDS",
        "DRAFT_CACHE_MAX_SIZE",
        "VALIDATOR_ENABLED",
        "VALIDATOR_MAX_MISSING_IGNORED",
        "APPROVED_EXAMPLES_PATH",
        "APPROVED_EXAMPLES_MAX",
        "REJECTED_EXAMPLES_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_settings_reads_required_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "style_rules.md").write_text("rules", encoding="utf-8")
    (prompts_dir / "style_examples.md").write_text("examples", encoding="utf-8")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "1, 2")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_MODEL", "model")

    settings = load_settings(base_dir=tmp_path)

    assert settings.telegram_bot_token == "token"
    assert settings.allowed_user_ids == frozenset({1, 2})
    assert settings.llm_model == "model"
    assert settings.llm_disable_thinking is False
    assert settings.llm_temperature == 0.2
    assert settings.draft_cache_ttl_seconds == 7200
    assert settings.validator_enabled is True
    assert settings.approved_examples_max == 30


def test_load_settings_defaults_moonshot_kimi_to_thinking_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "style_rules.md").write_text("rules", encoding="utf-8")
    (prompts_dir / "style_examples.md").write_text("examples", encoding="utf-8")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "1")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.5")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.moonshot.ai/v1")

    settings = load_settings(base_dir=tmp_path)

    assert settings.llm_disable_thinking is True
    assert settings.llm_temperature == 0.6


def test_load_settings_requires_allowed_user_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "style_rules.md").write_text("rules", encoding="utf-8")
    (prompts_dir / "style_examples.md").write_text("examples", encoding="utf-8")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_MODEL", "model")

    with pytest.raises(SettingsError):
        load_settings(base_dir=tmp_path)
