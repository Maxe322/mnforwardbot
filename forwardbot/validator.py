from __future__ import annotations

import re
from dataclasses import dataclass

from forwardbot.models import RewriteDraft

_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?(?:-?[A-Za-z]+)?\b")
_QUOTED_RE = re.compile(r'[„"”](.{3,}?)["“”]')
_ENTITY_TOKEN_RE = re.compile(r"\b[0-9A-ZÄÖÜ][0-9A-Za-zÄÖÜäöüß-]*\b")
_COMMON_ENTITY_WORDS = {
    "Der",
    "Die",
    "Das",
    "Ein",
    "Eine",
    "Einer",
    "Einem",
    "Einen",
    "Nach",
    "Mit",
    "Und",
    "Oder",
    "Aber",
    "Auch",
    "Laut",
    "Wie",
    "Im",
    "In",
    "Am",
    "An",
    "Auf",
    "Von",
    "Vor",
    "Zum",
    "Zur",
    "Für",
    "Fuer",
    "USA",
    "EU",
    "UN",
}
_SENTENCE_START_STOPWORDS = {
    "Der",
    "Die",
    "Das",
    "Ein",
    "Eine",
    "Einer",
    "Einem",
    "Einen",
    "Nach",
    "Mit",
    "Und",
    "Oder",
    "Aber",
    "Auch",
    "Laut",
    "Wie",
    "Im",
    "In",
    "Am",
    "An",
    "Auf",
    "Von",
    "Vor",
    "Zum",
    "Zur",
}


@dataclass(frozen=True, slots=True)
class ExtractedEntities:
    proper_nouns: set[str]
    numbers: set[str]
    quoted: set[str]


def extract_entities(text: str) -> ExtractedEntities:
    proper_nouns = _extract_proper_nouns(text)
    numbers = {match.group(0) for match in _NUMBER_RE.finditer(text)}
    quoted = {match.group(1).strip() for match in _QUOTED_RE.finditer(text) if match.group(1).strip()}
    return ExtractedEntities(proper_nouns=proper_nouns, numbers=numbers, quoted=quoted)


def validate_consistency(source_text: str, draft: RewriteDraft) -> list[str]:
    source = extract_entities(source_text)
    draft_text = "\n".join(part for part in ((draft.title or ""), *draft.paragraphs) if part)
    target = extract_entities(draft_text)

    missing: list[str] = []

    for number in sorted(source.numbers):
        if not _entity_matches(number, target.numbers):
            missing.append(number)

    for quoted in sorted(source.quoted):
        if not _entity_matches(quoted, target.quoted):
            missing.append(quoted)

    for entity in sorted(source.proper_nouns):
        if entity in _COMMON_ENTITY_WORDS:
            if not _entity_matches(entity, target.proper_nouns):
                missing.append(entity)
            continue
        if not _entity_matches(entity, target.proper_nouns):
            missing.append(entity)

    return missing


def _extract_proper_nouns(text: str) -> set[str]:
    tokens = list(_ENTITY_TOKEN_RE.finditer(text))
    if not tokens:
        return set()

    repeated_counts: dict[str, int] = {}
    for token in tokens:
        repeated_counts[token.group(0)] = repeated_counts.get(token.group(0), 0) + 1

    proper_nouns: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        value = token.group(0)
        if not _is_entity_candidate(text, token, repeated_counts):
            i += 1
            continue

        parts = [value]
        j = i + 1
        while j < len(tokens):
            gap = text[tokens[j - 1].end() : tokens[j].start()]
            if gap not in {" ", "-", " / "}:
                break
            next_value = tokens[j].group(0)
            if not _is_entity_candidate(text, tokens[j], repeated_counts):
                break
            parts.append(next_value)
            j += 1

        proper_nouns.add(" ".join(parts))
        i = j

    return proper_nouns


def _is_entity_candidate(text: str, token: re.Match[str], counts: dict[str, int]) -> bool:
    value = token.group(0)
    if value in _COMMON_ENTITY_WORDS:
        return False
    if any(char.isdigit() for char in value) or "-" in value:
        return True
    if counts.get(value, 0) > 1:
        return True
    if not value[:1].isupper():
        return False

    prefix = text[: token.start()].rstrip()
    if not prefix:
        return value not in _SENTENCE_START_STOPWORDS
    if prefix.endswith((".", "!", "?", ":", "\n")):
        return value not in _SENTENCE_START_STOPWORDS
    return True


def _entity_matches(needle: str, haystack: set[str]) -> bool:
    normalized_needle = needle.casefold()
    for item in haystack:
        normalized_item = item.casefold()
        if normalized_needle == normalized_item:
            return True
        if normalized_needle in normalized_item or normalized_item in normalized_needle:
            return True
    return False
