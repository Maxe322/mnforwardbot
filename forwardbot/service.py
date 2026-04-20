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
_FLAG_PREFIX_RE = re.compile(r"^(?:[\U0001F1E6-\U0001F1FF]{2}\s*)+")
_FLAG_ANY_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_TOKEN_RE = re.compile(r"[0-9A-Za-zÄÖÜäöüß]+")
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
_TRUNCATED_TITLE_ENDINGS = {
    "am",
    "an",
    "auf",
    "aus",
    "bei",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "durch",
    "ein",
    "eine",
    "einem",
    "einer",
    "für",
    "fuer",
    "gegen",
    "im",
    "in",
    "iranischer",
    "mit",
    "nach",
    "oder",
    "ohne",
    "über",
    "ueber",
    "und",
    "unter",
    "von",
    "vor",
    "wegen",
    "während",
    "waehrend",
    "zu",
    "zum",
    "zur",
}
_ASCII_TRANSLITERATION_HINTS = (
    "veroeffent",
    "bestaend",
    "verstoess",
    "grossbrit",
    "grossen",
    "gross",
    "muess",
    "fuer",
    "ueber",
    "unterstuetz",
    "aeusser",
    "behoerd",
    "praesident",
    "waehrend",
    "koennte",
    "mysterioes",
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

        quality_issues = _collect_quality_issues(draft)
        if quality_issues:
            repair_feedback = _build_repair_feedback(quality_issues)
            draft = await self._provider.rewrite(
                post,
                style_context,
                max_output_chars=max_chars,
                repair_feedback=repair_feedback,
            )
            draft = _normalize_structure(post, draft)

        return render_rewrite(draft, max_plain_text_chars=max_chars)


def _normalize_structure(post: IncomingPost, draft: RewriteDraft) -> RewriteDraft:
    normalized = draft

    repaired_title = _repair_title(post, normalized)
    if repaired_title != normalized.title:
        normalized = RewriteDraft(short_mode=normalized.short_mode, title=repaired_title, paragraphs=normalized.paragraphs)

    if _should_force_long_form(post, normalized):
        expanded = _expand_short_draft(normalized)
        if expanded is not None:
            normalized = expanded

    if not normalized.short_mode and len(normalized.paragraphs) == 1:
        sentences = _split_sentences(normalized.paragraphs[0])
        split_paragraphs = _group_sentences(sentences)
        should_split = len(normalized.paragraphs[0]) > 180 or len(sentences) >= 4
        if should_split and len(split_paragraphs) >= 2:
            normalized = RewriteDraft(short_mode=False, title=normalized.title, paragraphs=tuple(split_paragraphs))

    if not normalized.short_mode and normalized.title:
        cleaned_paragraphs = _dedupe_title_from_paragraphs(normalized.title, normalized.paragraphs)
        normalized = RewriteDraft(short_mode=False, title=normalized.title, paragraphs=cleaned_paragraphs)

    return normalized


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
    plain_compact = _strip_title_punctuation(plain)
    if len(plain_compact) < 10:
        return True
    if plain_compact.casefold() in _GENERIC_HEADLINES:
        return True
    if _ELLIPSIS_RE.search(normalized):
        return True
    if len(normalized) > 120:
        return True
    if normalized.count(".") >= 2:
        return True
    if _looks_truncated_title(plain_compact):
        return True
    return False


def _looks_truncated_title(title: str) -> bool:
    plain = _strip_title_punctuation(_strip_prefix_symbols(title))
    if not plain:
        return True
    if plain.endswith((".", "!", "?", '"', "“", "”")):
        return False
    if plain.endswith((":", ";", ",", "-", "–", "—")):
        return True

    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", plain)
    if not words:
        return False
    return words[-1].casefold() in _TRUNCATED_TITLE_ENDINGS


def _build_headline(text: str, fallback_title: str | None = None, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return fallback_title or ""

    prefix = _extract_prefix_symbols(fallback_title or normalized)
    body = _strip_prefix_symbols(normalized)
    body = _UPPER_LABEL_RE.sub("", body).strip()
    body = _strip_generic_headline_prefix(body).strip()

    sentences = _split_sentences(body[:600])
    first_sentence = sentences[0] if sentences else body
    first_sentence = _strip_title_punctuation(first_sentence)

    candidate = _first_headline_clause(first_sentence, limit=limit)
    if not candidate and fallback_title:
        candidate = _strip_title_punctuation(_strip_prefix_symbols(fallback_title))
    if not candidate:
        candidate = _strip_title_punctuation(body[:limit])

    candidate = _strip_generic_headline_prefix(candidate).strip()
    candidate = _trim_title_candidate(candidate, limit=limit)
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


def _limit_words(text: str, *, limit: int, max_words: int = 14) -> str:
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


def _trim_title_candidate(text: str, *, limit: int) -> str:
    candidate = _limit_words(text, limit=limit)
    while _looks_truncated_title(candidate):
        words = candidate.split()
        if len(words) <= 3:
            break
        candidate = " ".join(words[:-1]).strip()
        candidate = _strip_title_punctuation(candidate)
    return candidate


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


def _strip_generic_headline_prefix(text: str) -> str:
    return _GENERIC_HEADLINE_PREFIX_RE.sub("", text).strip()


def _dedupe_title_from_paragraphs(title: str, paragraphs: tuple[str, ...]) -> tuple[str, ...]:
    if not paragraphs:
        return paragraphs

    first = paragraphs[0].strip()
    cleaned_first = _strip_leading_flags(first)
    cleaned_first = _strip_title_prefix_from_paragraph(title, cleaned_first)

    cleaned: list[str] = []
    if cleaned_first:
        cleaned.append(cleaned_first)
    cleaned.extend(paragraph.strip() for paragraph in paragraphs[1:] if paragraph and paragraph.strip())
    return tuple(cleaned)


def _strip_title_prefix_from_paragraph(title: str, paragraph: str) -> str:
    stripped = paragraph.strip()
    if not stripped:
        return stripped

    for candidate in _title_candidates(title):
        remainder = _remove_leading_candidate(stripped, candidate)
        if remainder is not None:
            return remainder

    lead_clause, lead_remainder = _split_leading_clause(stripped)
    if lead_clause and _title_matches_paragraph(title, lead_clause):
        return lead_remainder

    first_sentence, sentence_remainder = _split_first_sentence(stripped)
    if sentence_remainder and _title_matches_paragraph(title, first_sentence):
        return sentence_remainder

    return stripped


def _title_candidates(title: str) -> tuple[str, ...]:
    raw = title.strip()
    plain = _strip_prefix_symbols(raw)
    plain = _strip_generic_headline_prefix(plain)
    return tuple(candidate for candidate in (raw, plain) if candidate)


def _remove_leading_candidate(text: str, candidate: str) -> str | None:
    cleaned_candidate = candidate.strip()
    if not cleaned_candidate:
        return None

    parts = [re.escape(part) for part in re.split(r"\s+", cleaned_candidate) if part]
    if not parts:
        return None

    pattern = r"^\s*" + r"\s+".join(parts) + r"(?:\s*[:;\-–—,.]\s*)?"
    match = re.match(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return text[match.end() :].strip()


def _split_leading_clause(text: str) -> tuple[str, str]:
    separators = (" — ", " – ", " - ", ": ", ". ", "! ", "? ")
    earliest_index: int | None = None
    earliest_separator = ""

    for separator in separators:
        index = text.find(separator)
        if index == -1:
            continue
        if earliest_index is None or index < earliest_index:
            earliest_index = index
            earliest_separator = separator

    if earliest_index is None:
        return text.strip(), ""

    lead = text[:earliest_index].strip()
    remainder = text[earliest_index + len(earliest_separator) :].strip()
    return lead, remainder


def _split_first_sentence(text: str) -> tuple[str, str]:
    sentences = _split_sentences(text)
    if not sentences:
        return "", ""
    first = sentences[0]
    if len(sentences) == 1:
        return first, ""

    remainder = text.strip()
    if remainder.startswith(first):
        remainder = remainder[len(first) :].lstrip(" \t")
    else:
        remainder = " ".join(sentences[1:]).strip()
    return first, remainder


def _title_matches_paragraph(title: str, paragraph: str) -> bool:
    title_normalized = _normalize_for_compare(title)
    paragraph_normalized = _normalize_for_compare(paragraph)
    if not title_normalized or not paragraph_normalized:
        return False

    if paragraph_normalized.startswith(title_normalized):
        return True
    if title_normalized in paragraph_normalized:
        return True

    title_tokens = _tokenize(title_normalized)
    paragraph_tokens = _tokenize(paragraph_normalized)
    if not title_tokens or not paragraph_tokens:
        return False

    intersection = title_tokens & paragraph_tokens
    jaccard = len(intersection) / len(title_tokens | paragraph_tokens)
    title_coverage = len(intersection) / len(title_tokens)
    return jaccard >= 0.85 or title_coverage >= 0.85


def _tokenize(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text)}


def _normalize_for_compare(text: str) -> str:
    no_prefix = _strip_prefix_symbols(text)
    no_flags = _FLAG_ANY_RE.sub("", no_prefix)
    no_generic = _strip_generic_headline_prefix(no_flags)
    collapsed = re.sub(r"\s+", " ", no_generic).strip()
    return _strip_title_punctuation(collapsed).casefold()


def _strip_leading_flags(text: str) -> str:
    return _FLAG_PREFIX_RE.sub("", text).strip()


def _starts_with_flags(text: str) -> bool:
    return bool(_FLAG_PREFIX_RE.match(text.strip()))


def _contains_ascii_transliteration(text: str) -> bool:
    lowered = text.casefold()
    return any(fragment in lowered for fragment in _ASCII_TRANSLITERATION_HINTS)


def _collect_quality_issues(draft: RewriteDraft) -> list[str]:
    issues: list[str] = []
    combined_text = " ".join(part for part in ((draft.title or ""), *draft.paragraphs) if part)

    if draft.short_mode:
        if _contains_ascii_transliteration(combined_text):
            issues.append("Verwende echte Umlaute und echtes ß statt ae/oe/ue/ss.")
        return issues

    if _title_needs_rewrite(draft.title):
        issues.append("Der title wirkt unvollständig, generisch oder abgeschnitten. Liefere eine vollständige, konkrete Headline.")

    first_paragraph = draft.paragraphs[0] if draft.paragraphs else ""
    if first_paragraph and _starts_with_flags(first_paragraph):
        issues.append("Der erste Absatz beginnt mit Flaggen-Emojis. Flaggen dürfen nur im title stehen.")
    if first_paragraph and draft.title and _title_matches_paragraph(draft.title, first_paragraph):
        issues.append("Der erste Absatz wiederholt den title zu stark. Beginne direkt mit neuen Informationen.")
    if _contains_ascii_transliteration(combined_text):
        issues.append("Verwende echte Umlaute und echtes ß statt ae/oe/ue/ss.")

    return list(dict.fromkeys(issues))


def _build_repair_feedback(issues: list[str]) -> str:
    bullets = "\n".join(f"- {issue}" for issue in issues)
    return (
        "Dein letzter Entwurf verletzt noch Formatregeln. "
        "Schreibe den kompletten Post neu und korrigiere dabei besonders diese Punkte:\n"
        f"{bullets}"
    )
