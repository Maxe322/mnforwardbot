from __future__ import annotations

import re

from forwardbot.config import Settings
from forwardbot.llm import AIProvider
from forwardbot.models import IncomingPost, RewriteDraft, RewriteResult
from forwardbot.rendering import render_rewrite
from forwardbot.style_loader import StyleRepository

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class RewriteService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: AIProvider,
        style_repository: StyleRepository,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._style_repository = style_repository

    async def rewrite(self, post: IncomingPost) -> RewriteResult:
        style_context = self._style_repository.load()
        max_chars = self._settings.telegram_caption_limit if post.has_media else self._settings.telegram_message_limit
        draft = await self._provider.rewrite(post, style_context, max_output_chars=max_chars)
        draft = _normalize_structure(post, draft)
        return render_rewrite(draft, max_plain_text_chars=max_chars)


def _normalize_structure(post: IncomingPost, draft: RewriteDraft) -> RewriteDraft:
    if _should_force_long_form(post, draft):
        expanded = _expand_short_draft(draft)
        if expanded is not None:
            return expanded

    if not draft.short_mode and len(draft.paragraphs) == 1:
        sentences = _split_sentences(draft.paragraphs[0])
        split_paragraphs = _group_sentences(sentences)
        should_split = len(draft.paragraphs[0]) > 180 or len(sentences) >= 4
        if should_split and len(split_paragraphs) >= 2:
            return RewriteDraft(short_mode=False, title=draft.title, paragraphs=tuple(split_paragraphs))

    return draft


def _should_force_long_form(post: IncomingPost, draft: RewriteDraft) -> bool:
    long_source = (
        len(post.source_text) >= 240
        or post.source_text.count("\n") >= 2
        or len(_split_sentences(post.source_text)) >= 4
    )
    if not long_source:
        return False
    if draft.short_mode or not draft.title:
        return True
    return len(draft.paragraphs) == 1 and len(draft.paragraphs[0]) > 280


def _expand_short_draft(draft: RewriteDraft) -> RewriteDraft | None:
    text = " ".join(part.strip() for part in draft.paragraphs if part and part.strip()).strip()
    if not text:
        return None

    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return None

    title = _truncate_title(sentences[0])
    paragraphs = _group_sentences(sentences[1:])
    if not title or not paragraphs:
        return None

    return RewriteDraft(short_mode=False, title=title, paragraphs=tuple(paragraphs))


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    return [chunk.strip() for chunk in _SENTENCE_SPLIT_RE.split(normalized) if chunk.strip()]


def _group_sentences(sentences: list[str], *, max_chars: int = 260, max_sentences_per_paragraph: int = 2) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        candidate = " ".join(current + [sentence]).strip()
        if current and (len(candidate) > max_chars or len(current) >= max_sentences_per_paragraph):
            paragraphs.append(" ".join(current).strip())
            current = [sentence]
            continue
        current.append(sentence)

    if current:
        paragraphs.append(" ".join(current).strip())

    return paragraphs


def _truncate_title(title: str, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", title).strip()
    if len(normalized) <= limit:
        return normalized
    shortened = normalized[: limit - 1].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened}…"
