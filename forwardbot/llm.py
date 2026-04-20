from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Protocol

import httpx

from forwardbot.models import IncomingPost, LLMError, RewriteDraft, RewriteResult, RewriteValidationError
from forwardbot.prompt_modifiers import PROMPT_MODIFIERS
from forwardbot.style_loader import StyleContext

logger = logging.getLogger(__name__)


class AIProvider(Protocol):
    async def rewrite(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        repair_feedback: str | None = None,
    ) -> RewriteDraft: ...

    async def rewrite_with_modifier(
        self,
        post: IncomingPost,
        current_draft: RewriteResult,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        modifier_key: str,
    ) -> RewriteDraft: ...

    async def rewrite_with_repair_hint(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        repair_hint: str,
    ) -> RewriteDraft: ...

    async def generate_headline_variants(
        self,
        post: IncomingPost,
        current_draft: RewriteResult,
        style_context: StyleContext,
    ) -> list[str]: ...

    async def close(self) -> None: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        disable_thinking: bool,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._disable_thinking = disable_thinking
        self._temperature = temperature
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def rewrite(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        repair_feedback: str | None = None,
    ) -> RewriteDraft:
        payload = self._build_rewrite_payload(
            post,
            style_context,
            max_output_chars=max_output_chars,
            repair_feedback=repair_feedback,
        )
        content = await self._request_completion(payload)
        return _parse_rewrite_draft(content)

    async def rewrite_with_modifier(
        self,
        post: IncomingPost,
        current_draft: RewriteResult,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        modifier_key: str,
    ) -> RewriteDraft:
        modifier_text = PROMPT_MODIFIERS.get(modifier_key)
        if modifier_text is None:
            raise ValueError(f"Unsupported modifier: {modifier_key}")
        payload = self._build_rewrite_payload(
            post,
            style_context,
            max_output_chars=max_output_chars,
            current_draft=current_draft,
            modifier_text=modifier_text,
        )
        content = await self._request_completion(payload)
        return _parse_rewrite_draft(content)

    async def rewrite_with_repair_hint(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        repair_hint: str,
    ) -> RewriteDraft:
        return await self.rewrite(
            post,
            style_context,
            max_output_chars=max_output_chars,
            repair_feedback=repair_hint,
        )

    async def generate_headline_variants(
        self,
        post: IncomingPost,
        current_draft: RewriteResult,
        style_context: StyleContext,
    ) -> list[str]:
        payload = self._build_variants_payload(post, current_draft, style_context)
        content = await self._request_completion(payload)
        return _parse_headline_variants(content)

    async def _request_completion(self, payload: dict[str, Any]) -> str:
        try:
            response_data = await self._post_chat_completion(payload | {"response_format": {"type": "json_object"}})
        except LLMError as exc:
            retry_temperature = _extract_required_temperature(str(exc))
            if retry_temperature is not None:
                logger.warning(
                    "Provider rejected temperature %.2f, retrying with required temperature %.2f.",
                    self._temperature,
                    retry_temperature,
                )
                payload = payload | {"temperature": retry_temperature}
                response_data = await self._post_chat_completion(payload | {"response_format": {"type": "json_object"}})
            elif not _looks_like_response_format_issue(exc):
                raise
            else:
                logger.warning("Provider rejected response_format=json_object, retrying without JSON mode.")
                response_data = await self._post_chat_completion(payload)

        try:
            return _extract_content(response_data)
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("AI response did not contain a usable completion payload.") from exc

    async def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": request_id,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"AI request failed before a response was received: {exc}") from exc

        if response.is_error:
            raise LLMError(f"AI request failed with status {response.status_code}: {response.text}")

        logger.info("LLM rewrite request completed (request_id=%s).", response.headers.get("x-request-id", request_id))
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError(f"AI returned a non-JSON response: {response.text[:500]}") from exc

    def _build_rewrite_payload(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
        repair_feedback: str | None = None,
        current_draft: RewriteResult | None = None,
        modifier_text: str | None = None,
    ) -> dict[str, Any]:
        system_prompt = _build_system_prompt(style_context)
        user_prompt = _build_user_prompt(
            post,
            max_output_chars=max_output_chars,
            repair_feedback=repair_feedback,
            current_draft=current_draft,
            modifier_text=modifier_text,
        )
        return self._build_payload(system_prompt=system_prompt, user_prompt=user_prompt)

    def _build_variants_payload(
        self,
        post: IncomingPost,
        current_draft: RewriteResult,
        style_context: StyleContext,
    ) -> dict[str, Any]:
        system_prompt = _build_system_prompt(style_context)
        user_prompt = _build_headline_variants_prompt(post, current_draft)
        return self._build_payload(system_prompt=system_prompt, user_prompt=user_prompt)

    def _build_payload(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self._disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        return payload


def _build_system_prompt(style_context: StyleContext) -> str:
    sections = [
        "Du bist ein deutscher Telegram-News-Redakteur.",
        "Deine Aufgabe ist es, fremdsprachige oder rohe Quellposts in einen sendefertigen deutschen Entwurf "
        "im Stil des Zielkanals umzuschreiben.\n\n"
        "Pflichtregeln:\n"
        "- Antworte ausschließlich als JSON-Objekt.\n"
        "- Erfinde keine Fakten und ergänze nichts, was nicht aus dem Quelltext hervorgeht.\n"
        "- Gib niemals Footer, Abo-Hinweise oder Hashtags aus.\n"
        "- Verwende kein Markdown und kein HTML in title oder paragraphs.\n"
        "- Verwende echte Umlaute und echtes ß, niemals ae/oe/ue/ss als Ersatz in normalen deutschen Wörtern.\n"
        "- short_mode=true nur dann, wenn der Beitrag so kurz ist, dass kein Titel und keine getrennten Absätze sinnvoll sind.\n"
        "- Wenn short_mode=true, muss title null sein und paragraphs genau einen kompakten Textblock enthalten.\n"
        "- Wenn short_mode=false, enthält title die komplette Titelzeile inklusive Flaggen oder Leit-Emoji, paragraphs enthält 1 bis 4 kurze Absätze.\n"
        "- Der title ist eine vollständige, konkrete Headline und niemals ein angefangener Satz oder ein kompletter Absatz.\n"
        "- Der title muss das eigentliche Ereignis benennen und darf kein leerer Platzhalter wie 'Geheime Entscheidung', 'Update' oder 'Eilmeldung' sein.\n"
        "- Der title darf nicht mit '...' oder '…' enden.\n"
        "- Der title soll nach den Flaggen möglichst zwischen 35 und 120 Zeichen lang sein.\n"
        "- Flaggen dürfen nur im title stehen, niemals erneut am Anfang des ersten Absatzes.\n"
        "- Der erste Absatz darf den title nicht wiederholen oder paraphrasieren und muss direkt mit neuen Informationen beginnen.\n"
        "- Emojis in den Absätzen nur sparsam einsetzen.\n"
        "- Halte dich an die Zeichenbegrenzung aus dem Nutzerprompt.\n\n"
        "JSON-Schema:\n"
        "{\n"
        '  "short_mode": true,\n'
        '  "title": null,\n'
        '  "paragraphs": ["..."]\n'
        "}\n\n"
        f"Stilregeln:\n{style_context.rules}",
        f"## Kanon-Stilbeispiele\n{style_context.examples}",
    ]
    if style_context.approved_examples:
        sections.append(f"## Zuletzt vom Redakteur freigegebene Beispiele\n{style_context.approved_examples}")
    return "\n\n".join(section for section in sections if section)


def _build_user_prompt(
    post: IncomingPost,
    *,
    max_output_chars: int,
    repair_feedback: str | None = None,
    current_draft: RewriteResult | None = None,
    modifier_text: str | None = None,
) -> str:
    source_payload = {
        "source_text": post.source_text,
        "source_chat_title": post.source_chat_title,
        "forwarded": post.forwarded,
        "has_media": post.has_media,
        "is_album": post.is_album,
        "max_output_characters": max_output_chars,
    }
    blocks = [
        "Formatiere den folgenden Quellpost als deutschen Kanalentwurf.",
        "Wichtig: Für Medienposts muss die Ausgabe so kurz bleiben, dass sie sicher als Telegram-Caption passt.",
        "Liefere nur JSON.",
        json.dumps(source_payload, ensure_ascii=False, indent=2),
    ]

    if current_draft is not None:
        blocks.append("Hier ist der bisherige Entwurf:")
        blocks.append(_serialize_current_draft(current_draft))

    if modifier_text:
        blocks.append(f"Zusätzliche Arbeitsanweisung:\n{modifier_text}")

    if repair_feedback:
        blocks.append(f"Zusätzlicher Korrekturhinweis für diese Neufassung:\n{repair_feedback}")

    return "\n\n".join(blocks)


def _build_headline_variants_prompt(post: IncomingPost, current_draft: RewriteResult) -> str:
    source_payload = {
        "source_text": post.source_text,
        "source_chat_title": post.source_chat_title,
        "forwarded": post.forwarded,
        "has_media": post.has_media,
        "is_album": post.is_album,
    }
    return (
        "Liefere NUR 3 alternative Titel-Vorschläge als JSON im Format "
        '{"variants": ["titel 1", "titel 2", "titel 3"]}. '
        "Keine Paragraphen, keine Zusätze.\n\n"
        f"{json.dumps(source_payload, ensure_ascii=False, indent=2)}\n\n"
        "Bisheriger Entwurf:\n"
        f"{_serialize_current_draft(current_draft)}"
    )


def _serialize_current_draft(current_draft: RewriteResult) -> str:
    payload = {
        "title": current_draft.title,
        "paragraphs": list(current_draft.paragraphs),
        "short_mode": current_draft.short_mode,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_content(response_data: dict[str, Any]) -> str:
    choices = response_data["choices"]
    message = choices[0]["message"]
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_chunks = [chunk.get("text", "") for chunk in content if isinstance(chunk, dict)]
        return "".join(text_chunks)
    raise LLMError("AI completion payload had an unsupported content format.")


def _parse_rewrite_draft(content: str) -> RewriteDraft:
    raw_json = _extract_json_object(content)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RewriteValidationError("AI returned invalid JSON.") from exc

    short_mode = bool(payload.get("short_mode"))
    title = payload.get("title")
    paragraphs = payload.get("paragraphs")

    if title is not None and not isinstance(title, str):
        raise RewriteValidationError("AI field 'title' must be a string or null.")

    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    if not isinstance(paragraphs, list) or not all(isinstance(item, str) for item in paragraphs):
        raise RewriteValidationError("AI field 'paragraphs' must be a list of strings.")

    cleaned = tuple(item.strip() for item in paragraphs if item and item.strip())
    if short_mode:
        if not cleaned:
            raise RewriteValidationError("Short mode rewrite must contain one text paragraph.")
        return RewriteDraft(short_mode=True, title=None, paragraphs=(cleaned[0],))

    if title is None or not str(title).strip():
        raise RewriteValidationError("Long-form rewrite requires a non-empty title.")
    return RewriteDraft(short_mode=False, title=str(title).strip(), paragraphs=cleaned)


def _parse_headline_variants(content: str) -> list[str]:
    raw_json = _extract_json_object(content)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RewriteValidationError("AI returned invalid JSON for headline variants.") from exc

    variants = payload.get("variants")
    if not isinstance(variants, list) or not all(isinstance(item, str) for item in variants):
        raise RewriteValidationError("AI field 'variants' must be a list of strings.")

    cleaned = [item.strip() for item in variants if item and item.strip()]
    if not cleaned:
        raise RewriteValidationError("AI must return at least one headline variant.")
    return cleaned[:3]


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RewriteValidationError("AI output did not contain a JSON object.")
    return stripped[start : end + 1]


def _looks_like_response_format_issue(exc: LLMError) -> bool:
    message = str(exc).lower()
    return "response_format" in message or "json_object" in message or "json schema" in message


def _extract_required_temperature(message: str) -> float | None:
    match = re.search(r"only\s+([0-9]+(?:\.[0-9]+)?)\s+is allowed", message.lower())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None
