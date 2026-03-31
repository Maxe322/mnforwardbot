from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import InputMediaPhoto, InputMediaVideo, Message

from forwardbot.album_buffer import AlbumBuffer
from forwardbot.config import Settings
from forwardbot.extraction import media_group_to_incoming_post, message_to_incoming_post
from forwardbot.llm import LLMError, OpenAICompatibleProvider
from forwardbot.models import IncomingPost, MediaItem, MediaKind, RewriteValidationError, UnsupportedMessageError
from forwardbot.service import RewriteService
from forwardbot.style_loader import StyleRepository

logger = logging.getLogger(__name__)


class ForwardBotApp:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        self._style_repository = StyleRepository(
            rules_path=settings.style_rules_path,
            examples_path=settings.style_examples_path,
        )
        self._rewrite_service = RewriteService(
            settings=settings,
            provider=self._provider,
            style_repository=self._style_repository,
        )
        self._bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dispatcher = Dispatcher()
        self._album_buffer = AlbumBuffer(
            delay_seconds=settings.album_collect_window_seconds,
            callback=self._process_album_messages,
        )
        self._dispatcher.include_router(self._build_router())

    async def run(self) -> None:
        logger.info("Starting Telegram bot polling.")
        await self._dispatcher.start_polling(self._bot)

    async def shutdown(self) -> None:
        await self._album_buffer.close()
        await self._provider.close()
        await self._bot.session.close()

    def _build_router(self) -> Router:
        router = Router()

        @router.message(CommandStart())
        async def handle_start(message: Message) -> None:
            if not await self._ensure_allowed(message):
                return
            await message.answer(
                "Sende mir einen weitergeleiteten Text-, Foto-, Video- oder Album-Post. "
                "Ich schicke dir einen deutschen Entwurf mit den Originalmedien zurück."
            )

        @router.message()
        async def handle_message(message: Message) -> None:
            if not await self._ensure_allowed(message):
                return

            if message.media_group_id:
                await self._album_buffer.add(message)
                return

            await self._process_single_message(message)

        return router

    async def _ensure_allowed(self, message: Message) -> bool:
        sender = message.from_user
        if sender is None or sender.id not in self._settings.allowed_user_ids:
            await message.answer("Du bist für diesen Bot nicht freigeschaltet.")
            return False
        return True

    async def _process_single_message(self, message: Message) -> None:
        try:
            post = message_to_incoming_post(message)
            await self._rewrite_and_send(chat_id=message.chat.id, post=post)
        except UnsupportedMessageError as exc:
            await message.answer(str(exc))
        except (LLMError, RewriteValidationError) as exc:
            logger.warning("Rewrite failed for message %s: %s", message.message_id, exc)
            await message.answer("Die Umschreibung hat nicht geklappt. Bitte versuche es gleich noch einmal.")
        except Exception:
            logger.exception("Unexpected processing failure for message %s.", message.message_id)
            await message.answer("Beim Verarbeiten des Beitrags ist ein unerwarteter Fehler aufgetreten.")

    async def _process_album_messages(self, messages: list[Message]) -> None:
        lead_message = min(messages, key=lambda item: item.message_id)
        try:
            post = media_group_to_incoming_post(messages)
            await self._rewrite_and_send(chat_id=lead_message.chat.id, post=post)
        except UnsupportedMessageError as exc:
            await self._bot.send_message(chat_id=lead_message.chat.id, text=str(exc))
        except (LLMError, RewriteValidationError) as exc:
            logger.warning("Rewrite failed for media group %s: %s", lead_message.media_group_id, exc)
            await self._bot.send_message(
                chat_id=lead_message.chat.id,
                text="Die Umschreibung des Albums hat nicht geklappt. Bitte versuche es gleich noch einmal.",
            )
        except Exception:
            logger.exception("Unexpected processing failure for media group %s.", lead_message.media_group_id)
            await self._bot.send_message(
                chat_id=lead_message.chat.id,
                text="Beim Verarbeiten des Albums ist ein unerwarteter Fehler aufgetreten.",
            )

    async def _rewrite_and_send(self, *, chat_id: int, post: IncomingPost) -> None:
        result = await self._rewrite_service.rewrite(post)

        if not post.has_media:
            await self._bot.send_message(chat_id=chat_id, text=result.formatted_html, disable_web_page_preview=True)
            return

        if post.is_album:
            await self._send_album(chat_id=chat_id, media_items=post.media_items, caption=result.formatted_html)
            return

        await self._send_single_media(chat_id=chat_id, media_item=post.media_items[0], caption=result.formatted_html)

    async def _send_single_media(self, *, chat_id: int, media_item: MediaItem, caption: str) -> None:
        if media_item.kind is MediaKind.PHOTO:
            await self._bot.send_photo(
                chat_id=chat_id,
                photo=media_item.file_id,
                caption=caption or None,
                has_spoiler=media_item.has_spoiler,
            )
            return

        if media_item.kind is MediaKind.VIDEO:
            await self._bot.send_video(
                chat_id=chat_id,
                video=media_item.file_id,
                caption=caption or None,
                has_spoiler=media_item.has_spoiler,
                supports_streaming=media_item.supports_streaming,
            )
            return

        raise UnsupportedMessageError("Dieser Medientyp kann nicht zurückgesendet werden.")

    async def _send_album(self, *, chat_id: int, media_items: tuple[MediaItem, ...], caption: str) -> None:
        media_payload = []
        for index, item in enumerate(media_items):
            item_caption = caption if index == 0 and caption else None
            if item.kind is MediaKind.PHOTO:
                media_payload.append(
                    InputMediaPhoto(
                        media=item.file_id,
                        caption=item_caption,
                        has_spoiler=item.has_spoiler,
                        parse_mode=ParseMode.HTML if item_caption else None,
                    )
                )
                continue

            if item.kind is MediaKind.VIDEO:
                media_payload.append(
                    InputMediaVideo(
                        media=item.file_id,
                        caption=item_caption,
                        has_spoiler=item.has_spoiler,
                        supports_streaming=item.supports_streaming,
                        parse_mode=ParseMode.HTML if item_caption else None,
                    )
                )
                continue

            raise UnsupportedMessageError("Dieses Album enthält einen nicht unterstützten Medientyp.")

        await self._bot.send_media_group(chat_id=chat_id, media=media_payload)
