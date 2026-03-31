from __future__ import annotations

from forwardbot.config import Settings
from forwardbot.llm import AIProvider
from forwardbot.models import IncomingPost, RewriteResult
from forwardbot.rendering import render_rewrite
from forwardbot.style_loader import StyleRepository


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
        return render_rewrite(draft, max_plain_text_chars=max_chars)

