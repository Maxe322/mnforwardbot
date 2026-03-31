from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Protocol

import httpx

from forwardbot.models import IncomingPost, LLMError, RewriteDraft, RewriteValidationError
from forwardbot.style_loader import StyleContext

logger = logging.getLogger(__name__)


class AIProvider(Protocol):
    async def rewrite(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
    ) -> RewriteDraft: ...

    async def close(self) -> None: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def rewrite(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
    ) -> RewriteDraft:
        payload = self._build_payload(post, style_context, max_output_chars=max_output_chars)
        content = await self._request_completion(payload)
        return _parse_rewrite_draft(content)

    async def _request_completion(self, payload: dict[str, Any]) -> str:
        try:
            response_data = await self._post_chat_completion(payload | {"response_format": {"type": "json_object"}})
        except LLMError as exc:
            if not _looks_like_response_format_issue(exc):
                raise
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
        return response.json()

    def _build_payload(
        self,
        post: IncomingPost,
        style_context: StyleContext,
        *,
        max_output_chars: int,
    ) -> dict[str, Any]:
        system_prompt = _build_system_prompt(style_context)
        user_prompt = _build_user_prompt(post, max_output_chars=max_output_chars)

        return {
            "model": self._model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }


def _build_system_prompt(style_context: StyleContext) -> str:
    return (
        "Du bist ein deutscher Telegram-News-Redakteur.\n"
        "Deine Aufgabe ist es, fremdsprachige oder rohe Quellposts in einen sendefertigen deutschen Entwurf "
        "im Stil des Zielkanals umzuschreiben.\n\n"
        "Pflichtregeln:\n"
        "- Antworte ausschließlich als JSON-Objekt.\n"
        "- Erfinde keine Fakten und ergänze nichts, was nicht aus dem Quelltext hervorgeht.\n"
        "- Gib niemals Footer, Abo-Hinweise oder Hashtags aus.\n"
        "- Verwende kein Markdown und kein HTML in title oder paragraphs.\n"
        "- short_mode=true nur dann, wenn der Beitrag so kurz ist, dass kein Titel und keine getrennten Absätze sinnvoll sind.\n"
        "- Wenn short_mode=true, muss title null sein und paragraphs genau einen kompakten Textblock enthalten.\n"
        "- Wenn short_mode=false, enthält title die komplette Titelzeile inklusive Flaggen/Leit-Emoji, paragraphs enthält 1 bis 4 kurze Absätze.\n"
        "- Emojis in den Absätzen nur sparsam einsetzen.\n"
        "- Halte dich an die Zeichenbegrenzung aus dem Nutzerprompt.\n\n"
        "JSON-Schema:\n"
        "{\n"
        '  "short_mode": true,\n'
        '  "title": null,\n'
        '  "paragraphs": ["..."]\n'
        "}\n\n"
        f"Stilregeln:\n{style_context.rules}\n\n"
        f"Beispielposts:\n{style_context.examples}"
    )


def _build_user_prompt(post: IncomingPost, *, max_output_chars: int) -> str:
    source_payload = {
        "source_text": post.source_text,
        "source_chat_title": post.source_chat_title,
        "forwarded": post.forwarded,
        "has_media": post.has_media,
        "is_album": post.is_album,
        "max_output_characters": max_output_chars,
    }
    return (
        "Formatiere den folgenden Quellpost als deutschen Kanalentwurf.\n"
        "Wichtig: Für Medienposts muss die Ausgabe so kurz bleiben, dass sie sicher als Telegram-Caption passt.\n"
        "Liefere nur JSON.\n\n"
        f"{json.dumps(source_payload, ensure_ascii=False, indent=2)}"
    )


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
