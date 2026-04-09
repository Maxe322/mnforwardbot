from __future__ import annotations

import re

from forwardbot.config import Settings
from forwardbot.llm import AIProvider
from forwardbot.models import IncomingPost, RewriteDraft, RewriteResult
from forwardbot.rendering import render_rewrite
from forwardbot.style_loader import StyleRepository

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_ELLIPSIS_RE = re.compile(r"(?:\.{3,}|\u2026+)")
_UPPER_LABEL_RE = re.compile(r"^(?:[A-Z]{2,20}|BIG|BREAKING|UPDATE|EIL|EILMELDUNG)\s*:\s*")
_HEADLINE_SPLIT_RE = re.compile(r"\s*(?:[\u2014\u2013:;]|\s-\s|\s\|\s)\s*")
_PREFIX_SYMBOL_RE = re.compile(r"^[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\s]+")
_GENERIC_HEADLINES = {
    "geheime entscheidung",
    "entscheidung",
    "update",
    "lageupdate",
    "eilmeldung",
    "breaking",
    "wichtig",
    "alarm",
    "sensation",
}
_GENERIC_HEADLINE_PREFIX_RE = re.compile(
    r"^(?:(?:geheime entscheidung|entscheidung|update|lageupdate|eilmeldung|breaking|wichtig|alarm|sensation)\s*[:\-]\s*)+",
    re.IGNORECASE,
)


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
    repaired_title = _repair_title(post, draft)
    if repaired_title != draft.title:
        draft = RewriteDraft(short_mode=draft.short_mode, title=repaired_title, paragraphs=draft.paragraphs)

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

    if not draft.short_mode and draft.title:
        deduped_paragraphs = _dedupe_title_from_paragraphs(draft.title, draft.paragraphs)
        if deduped_paragraphs != draft.paragraphs:
            return RewriteDraft(short_mode=False, title=draft.title, paragraphs=deduped_paragraphs)

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

    title = _build_headline(text, fallback_title=draft.title)
    if not title:
        return None

    title_body = _strip_title_punctuation(_strip_prefix_symbols(title)).casefold()
    first_sentence_body = _strip_title_punctuation(_strip_prefix_symbols(sentences[0])).casefold()
    remaining_sentences = sentences[1:] if title_body == first_sentence_body else sentences
    paragraphs = _group_sentences(remaining_sentences)
    if not paragraphs:
        return None

    return RewriteDraft(short_mode=False, title=title, paragraphs=tuple(paragraphs))


def _repair_title(post: IncomingPost, draft: RewriteDraft) -> str | None:
    if draft.short_mode:
        return draft.title
    if draft.title and not _title_needs_rewrite(draft.title):
        return draft.title

    full_text = " ".join(part.strip() for part in draft.paragraphs if part and part.strip()).strip() or post.source_text
    if not full_text:
        return draft.title
    return _build_headline(full_text, fallback_title=draft.title)


def _title_needs_rewrite(title: str | None) -> bool:
    if title is None:
        return True

    normalized = re.sub(r"\s+", " ", title).strip()
    if not normalized:
        return True

    plain = _strip_prefix_symbols(normalized)
    if len(plain) < 10:
        return True
    if plain.casefold() in _GENERIC_HEADLINES:
        return True
    if _ELLIPSIS_RE.search(normalized):
        return True
    if len(normalized) > 110:
        return True
    if normalized.count(".") >= 2:
        return True
    return False


def _build_headline(text: str, fallback_title: str | None = None, limit: int = 96) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return fallback_title or ""

    prefix = _extract_prefix_symbols(fallback_title or normalized)
    body = _strip_prefix_symbols(normalized)
    body = _UPPER_LABEL_RE.sub("", body).strip()
    body = _GENERIC_HEADLINE_PREFIX_RE.sub("", body).strip()

    sentences = _split_sentences(body[:500])
    first_sentence = sentences[0] if sentences else body
    first_sentence = _strip_title_punctuation(first_sentence)

    candidate = _first_headline_clause(first_sentence, limit=limit)
    if not candidate and fallback_title:
        candidate = _strip_title_punctuation(_strip_prefix_symbols(fallback_title))
    if not candidate:
        candidate = _strip_title_punctuation(body[:limit])

    return f"{prefix} {candidate}".strip() if prefix else candidate


def _first_headline_clause(text: str, *, limit: int) -> str:
    sentence = _strip_title_punctuation(text)
    if len(sentence) <= limit:
        return sentence

    for part in _HEADLINE_SPLIT_RE.split(sentence):
        cleaned = _strip_title_punctuation(part)
        if 18 <= len(cleaned) <= limit:
            return cleaned

    for part in sentence.split(","):
        cleaned = _strip_title_punctuation(part)
        if 18 <= len(cleaned) <= limit:
            return cleaned

    return _limit_words(sentence, limit=limit)


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


def _limit_words(text: str, *, limit: int, max_words: int = 12) -> str:
    words = text.split()
    collected: list[str] = []
    current_len = 0

    for word in words:
        projected_len = current_len + (1 if collected else 0) + len(word)
        if collected and (projected_len > limit or len(collected) >= max_words):
            break
        collected.append(word)
        current_len = projected_len

    limited = " ".join(collected).strip()
    if limited:
        return _strip_title_punctuation(limited)
    return _strip_title_punctuation(text[:limit])


def _extract_prefix_symbols(text: str) -> str:
    if not text:
        return ""
    match = _PREFIX_SYMBOL_RE.match(text)
    return match.group(0).strip() if match else ""


def _strip_prefix_symbols(text: str) -> str:
    if not text:
        return ""
    match = _PREFIX_SYMBOL_RE.match(text)
    if not match:
        return text.strip()
    return text[match.end() :].strip()


def _strip_title_punctuation(text: str) -> str:
    return text.strip().strip(" .,!?;:-\u2013\u2014")


def _dedupe_title_from_paragraphs(title: str, paragraphs: tuple[str, ...]) -> tuple[str, ...]:
    if not paragraphs:
        return paragraphs

    first = paragraphs[0].strip()
    remainder = _strip_title_prefix_from_paragraph(title, first)
    if remainder == first:
        return paragraphs

    cleaned: list[str] = []
    if remainder:
        cleaned.append(remainder)
    cleaned.extend(paragraph for paragraph in paragraphs[1:] if paragraph.strip())
    return tuple(cleaned)


def _strip_title_prefix_from_paragraph(title: str, paragraph: str) -> str:
    title_plain = _normalize_for_compare(title)
    paragraph_plain = _normalize_for_compare(paragraph)

    if not title_plain or not paragraph_plain.startswith(title_plain):
        return paragraph

    stripped = paragraph.strip()
    title_text = title.strip()

    if stripped.startswith(title_text):
        remainder = stripped[len(title_text) :].lstrip(" \t-–—:;,.")
        return remainder.strip()

    paragraph_body = _strip_prefix_symbols(stripped)
    title_body = _strip_prefix_symbols(title_text)
    if paragraph_body.startswith(title_body):
        remainder = paragraph_body[len(title_body) :].lstrip(" \t-–—:;,.")
        return remainder.strip()

    return paragraph


def _normalize_for_compare(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", _strip_prefix_symbols(text)).strip()
    return _strip_title_punctuation(collapsed).casefold()
