from __future__ import annotations

import html
import re

from forwardbot.models import RewriteDraft, RewriteResult

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FOOTER_PATTERNS = (
    re.compile(r"^\s*#\w+", re.IGNORECASE),
    re.compile(r"verpasse nichts", re.IGNORECASE),
    re.compile(r"abonniere hier", re.IGNORECASE),
)


def render_rewrite(draft: RewriteDraft, max_plain_text_chars: int) -> RewriteResult:
    title = _sanitize_fragment(draft.title)
    paragraphs = tuple(filter(None, (_sanitize_fragment(paragraph) for paragraph in draft.paragraphs)))

    if draft.short_mode or not title:
        short_text = _truncate_plain_text(" ".join(paragraphs).strip(), max_plain_text_chars)
        return RewriteResult(
            short_mode=True,
            title=None,
            paragraphs=(short_text,) if short_text else (),
            formatted_html=html.escape(short_text),
        )

    title = _truncate_plain_text(title, min(max_plain_text_chars, 280))
    fitted_paragraphs = _fit_paragraphs(title, paragraphs, max_plain_text_chars)
    formatted_html = _compose_long_form(title, fitted_paragraphs)

    return RewriteResult(
        short_mode=False,
        title=title,
        paragraphs=fitted_paragraphs,
        formatted_html=formatted_html,
    )


def plain_text_length(formatted_html: str) -> int:
    text = html.unescape(_HTML_TAG_RE.sub("", formatted_html))
    return len(text)


def _compose_long_form(title: str, paragraphs: tuple[str, ...]) -> str:
    blocks = [f"<b>{html.escape(title)}</b>"]
    blocks.extend(html.escape(paragraph) for paragraph in paragraphs if paragraph)
    return "\n\n".join(blocks)


def _fit_paragraphs(title: str, paragraphs: tuple[str, ...], limit: int) -> tuple[str, ...]:
    fixed_budget = len(title)
    available = max(limit - fixed_budget, 0)
    if available <= 2:
        return ()

    accepted: list[str] = []
    used = 0
    for paragraph in paragraphs:
        separator_len = 2
        needed = separator_len + len(paragraph)
        remaining = available - used

        if needed <= remaining:
            accepted.append(paragraph)
            used += needed
            continue

        if remaining > separator_len + 20:
            accepted.append(_truncate_plain_text(paragraph, remaining - separator_len))
        break

    return tuple(accepted)


def _sanitize_fragment(value: str | None) -> str | None:
    if value is None:
        return None
    normalized_lines: list[str] = []
    for raw_line in value.replace("\r\n", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if _is_footer_line(line):
            continue
        normalized_lines.append(line)
    cleaned = "\n".join(normalized_lines).strip()
    return cleaned or None


def _is_footer_line(value: str) -> bool:
    return any(pattern.search(value) for pattern in _FOOTER_PATTERNS)


def _truncate_plain_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    if limit <= 1:
        return normalized[:limit]
    slice_ = normalized[: limit - 1].rstrip()
    if " " in slice_:
        slice_ = slice_.rsplit(" ", 1)[0]
    return f"{slice_}…"
