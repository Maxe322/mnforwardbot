from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class SettingsError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    allowed_user_ids: frozenset[int]
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_disable_thinking: bool
    llm_temperature: float
    llm_timeout_seconds: float
    log_level: str
    album_collect_window_seconds: float
    telegram_caption_limit: int
    telegram_message_limit: int
    style_rules_path: Path
    style_examples_path: Path


def load_settings(base_dir: Path | None = None) -> Settings:
    root = base_dir or Path(__file__).resolve().parent.parent
    token = _require_env("TELEGRAM_BOT_TOKEN")
    allowed_user_ids = _parse_allowed_user_ids(_require_env("ALLOWED_USER_IDS"))
    llm_api_key = _require_env("LLM_API_KEY")
    llm_model = _require_env("LLM_MODEL")
    llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    llm_disable_thinking = _parse_bool(
        "LLM_DISABLE_THINKING",
        default=("moonshot.ai" in llm_base_url and llm_model == "kimi-k2.5"),
    )
    llm_temperature = _parse_float(
        "LLM_TEMPERATURE",
        0.6 if ("moonshot.ai" in llm_base_url and llm_model == "kimi-k2.5") else 0.2,
    )
    llm_timeout_seconds = _parse_float("LLM_TIMEOUT_SECONDS", 45.0)
    album_collect_window_seconds = _parse_float("ALBUM_COLLECT_WINDOW_SECONDS", 1.2)
    telegram_caption_limit = _parse_int("TELEGRAM_CAPTION_LIMIT", 950)
    telegram_message_limit = _parse_int("TELEGRAM_MESSAGE_LIMIT", 4000)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    style_rules_path = (root / os.getenv("STYLE_RULES_PATH", "prompts/style_rules.md")).resolve()
    style_examples_path = (root / os.getenv("STYLE_EXAMPLES_PATH", "prompts/style_examples.md")).resolve()

    return Settings(
        telegram_bot_token=token,
        allowed_user_ids=allowed_user_ids,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_disable_thinking=llm_disable_thinking,
        llm_temperature=llm_temperature,
        llm_timeout_seconds=llm_timeout_seconds,
        log_level=log_level,
        album_collect_window_seconds=album_collect_window_seconds,
        telegram_caption_limit=telegram_caption_limit,
        telegram_message_limit=telegram_message_limit,
        style_rules_path=style_rules_path,
        style_examples_path=style_examples_path,
    )


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SettingsError(f"Missing required environment variable: {name}")
    return value


def _parse_allowed_user_ids(raw: str) -> frozenset[int]:
    values: set[int] = set()
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        try:
            values.add(int(chunk))
        except ValueError as exc:
            raise SettingsError(f"Invalid Telegram user ID in ALLOWED_USER_IDS: {chunk}") from exc
    if not values:
        raise SettingsError("ALLOWED_USER_IDS must contain at least one Telegram user ID.")
    return frozenset(values)


def _parse_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"Environment variable {name} must be a number.") from exc


def _parse_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"Environment variable {name} must be an integer.") from exc


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"Environment variable {name} must be a boolean value.")
