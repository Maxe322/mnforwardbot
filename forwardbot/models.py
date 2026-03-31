from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class MediaItem:
    kind: MediaKind
    file_id: str
    has_spoiler: bool = False
    supports_streaming: bool = False


@dataclass(frozen=True, slots=True)
class IncomingPost:
    sender_user_id: int
    chat_id: int
    source_text: str
    media_items: tuple[MediaItem, ...] = ()
    media_group_id: str | None = None
    source_chat_title: str | None = None
    source_message_id: int | None = None
    forwarded: bool = False

    @property
    def has_media(self) -> bool:
        return bool(self.media_items)

    @property
    def is_album(self) -> bool:
        return len(self.media_items) > 1


@dataclass(frozen=True, slots=True)
class RewriteDraft:
    short_mode: bool
    title: str | None
    paragraphs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RewriteResult:
    short_mode: bool
    title: str | None
    paragraphs: tuple[str, ...]
    formatted_html: str


class UnsupportedMessageError(RuntimeError):
    """Raised when a Telegram message cannot be transformed into a rewrite job."""


class RewriteValidationError(ValueError):
    """Raised when the LLM returned malformed data."""


class LLMError(RuntimeError):
    """Raised when the configured AI provider cannot complete a rewrite."""

