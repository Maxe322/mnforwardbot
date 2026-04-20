from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Message

from forwardbot.album_buffer import AlbumBuffer
from forwardbot.approved_store import ApprovedExample, ApprovedStore
from forwardbot.config import Settings
from forwardbot.draft_cache import CachedDraft, DraftCache
from forwardbot.extraction import media_group_to_incoming_post, message_to_incoming_post
from forwardbot.keyboards import build_draft_keyboard, build_headline_picker, parse_callback
from forwardbot.llm import LLMError, OpenAICompatibleProvider
from forwardbot.models import IncomingPost, MediaItem, MediaKind, RewriteResult, RewriteValidationError, UnsupportedMessageError
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
            disable_thinking=settings.llm_disable_thinking,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        self._approved_store = ApprovedStore(settings.approved_examples_path, max_examples=settings.approved_examples_max)
        self._style_repository = StyleRepository(
            rules_path=settings.style_rules_path,
            examples_path=settings.style_examples_path,
            approved_store=self._approved_store,
            approved_limit=settings.approved_examples_max,
        )
        self._rewrite_service = RewriteService(
            settings=settings,
            provider=self._provider,
            style_repository=self._style_repository,
        )
        self._draft_cache = DraftCache(
            ttl_seconds=settings.draft_cache_ttl_seconds,
            max_size=settings.draft_cache_max_size,
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

        @router.callback_query(F.data.startswith("d:"))
        async def handle_draft_callback(callback_query: CallbackQuery) -> None:
            await self._handle_draft_callback(callback_query)

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
        await self._send_draft(chat_id=chat_id, post=post, result=result)

    async def _send_draft(self, *, chat_id: int, post: IncomingPost, result: RewriteResult) -> None:
        draft_id = secrets.token_urlsafe(6)
        keyboard = build_draft_keyboard(draft_id)

        if not post.has_media:
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=result.formatted_html,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
            self._draft_cache.put(
                CachedDraft(
                    draft_id=draft_id,
                    sender_user_id=post.sender_user_id,
                    chat_id=chat_id,
                    message_id=sent.message_id,
                    incoming=post,
                    current_result=result,
                    created_at=datetime.now(timezone.utc),
                    edit_mode="text",
                )
            )
            return

        if post.is_album:
            await self._send_album(chat_id=chat_id, media_items=post.media_items, caption=result.formatted_html)
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=result.formatted_html,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
            self._draft_cache.put(
                CachedDraft(
                    draft_id=draft_id,
                    sender_user_id=post.sender_user_id,
                    chat_id=chat_id,
                    message_id=sent.message_id,
                    incoming=post,
                    current_result=result,
                    created_at=datetime.now(timezone.utc),
                    edit_mode="text",
                )
            )
            return

        sent = await self._send_single_media(
            chat_id=chat_id,
            media_item=post.media_items[0],
            caption=result.formatted_html,
            reply_markup=keyboard,
        )
        self._draft_cache.put(
            CachedDraft(
                draft_id=draft_id,
                sender_user_id=post.sender_user_id,
                chat_id=chat_id,
                message_id=sent.message_id,
                incoming=post,
                current_result=result,
                created_at=datetime.now(timezone.utc),
                edit_mode="caption",
            )
        )

    async def _send_single_media(
        self,
        *,
        chat_id: int,
        media_item: MediaItem,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message:
        if media_item.kind is MediaKind.PHOTO:
            return await self._bot.send_photo(
                chat_id=chat_id,
                photo=media_item.file_id,
                caption=caption or None,
                has_spoiler=media_item.has_spoiler,
                reply_markup=reply_markup,
            )

        if media_item.kind is MediaKind.VIDEO:
            return await self._bot.send_video(
                chat_id=chat_id,
                video=media_item.file_id,
                caption=caption or None,
                has_spoiler=media_item.has_spoiler,
                supports_streaming=media_item.supports_streaming,
                reply_markup=reply_markup,
            )

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

    async def _handle_draft_callback(self, callback_query: CallbackQuery) -> None:
        if callback_query.data is None:
            await callback_query.answer("Ungültige Aktion.", show_alert=True)
            return

        try:
            action, draft_id, arg = parse_callback(callback_query.data)
        except ValueError:
            await callback_query.answer("Ungültige Aktion.", show_alert=True)
            return

        cached = self._draft_cache.get(draft_id)
        if cached is None:
            await callback_query.answer("Entwurf abgelaufen.", show_alert=True)
            return

        user = callback_query.from_user
        if user is None or user.id != cached.sender_user_id:
            await callback_query.answer("Dieser Entwurf gehört dir nicht.", show_alert=True)
            return

        try:
            if action == "ok":
                await self._handle_approve(callback_query, cached)
                return
            if action == "no":
                await self._handle_reject(callback_query, cached)
                return
            if action == "bk":
                self._draft_cache.clear_headline_variants(draft_id)
                await self._edit_reply_markup_only(cached, build_draft_keyboard(draft_id))
                await callback_query.answer("Zurück zum Entwurf.")
                return

            if action == "nh":
                await callback_query.answer("⏳ Wird aktualisiert…")
                variants = await self._rewrite_service.generate_headline_variants(cached.incoming, cached.current_result)
                self._draft_cache.set_headline_variants(draft_id, variants)
                await self._edit_reply_markup_only(cached, build_headline_picker(draft_id, variants))
                return

            if action == "nhP":
                if arg is None:
                    await callback_query.answer("Variante fehlt.", show_alert=True)
                    return
                index = int(arg)
                variants = cached.headline_variants
                if index < 0 or index >= len(variants):
                    await callback_query.answer("Variante nicht mehr verfügbar.", show_alert=True)
                    return
                await callback_query.answer("⏳ Wird aktualisiert…")
                new_result = self._rewrite_service.apply_headline_variant(cached.incoming, cached.current_result, variants[index])
                self._draft_cache.update(draft_id, new_result)
                self._draft_cache.clear_headline_variants(draft_id)
                await self._edit_cached_message(cached, new_result, build_draft_keyboard(draft_id))
                return

            if action in {"sh", "lg", "fc", "em", "rg"}:
                await callback_query.answer("⏳ Wird aktualisiert…")
                new_result = await self._rewrite_service.rewrite_with_modifier(cached.incoming, cached.current_result, action)
                self._draft_cache.update(draft_id, new_result)
                self._draft_cache.clear_headline_variants(draft_id)
                await self._edit_cached_message(cached, new_result, build_draft_keyboard(draft_id))
                return

            await callback_query.answer("Unbekannte Aktion.", show_alert=True)
        except (LLMError, RewriteValidationError) as exc:
            logger.warning("Draft callback rewrite failed for %s (%s): %s", draft_id, action, exc)
            await callback_query.answer("Die Umschreibung hat nicht geklappt.", show_alert=True)
        except Exception:
            logger.exception("Unexpected draft callback failure for %s (%s).", draft_id, action)
            await callback_query.answer("Beim Bearbeiten ist ein Fehler aufgetreten.", show_alert=True)

    async def _handle_approve(self, callback_query: CallbackQuery, cached: CachedDraft) -> None:
        self._approved_store.add(
            ApprovedExample(
                title=cached.current_result.title or "",
                paragraphs=list(cached.current_result.paragraphs),
                source_hint=cached.incoming.source_chat_title,
                approved_at=datetime.now(timezone.utc),
            )
        )
        await self._clear_reply_markup(cached)
        await callback_query.answer("Gespeichert als Stilbeispiel.")

    async def _handle_reject(self, callback_query: CallbackQuery, cached: CachedDraft) -> None:
        logger.info(
            "negative_feedback",
            extra={
                "draft_id": cached.draft_id,
                "source_chat_title": cached.incoming.source_chat_title,
                "title": cached.current_result.title,
            },
        )
        self._append_jsonl(
            self._settings.rejected_examples_path,
            {
                "draft_id": cached.draft_id,
                "source_chat_title": cached.incoming.source_chat_title,
                "source_text": cached.incoming.source_text,
                "title": cached.current_result.title,
                "paragraphs": list(cached.current_result.paragraphs),
                "rejected_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await callback_query.answer("Danke, notiert.")

    async def _edit_cached_message(
        self,
        cached: CachedDraft,
        new_result: RewriteResult,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        if new_result.formatted_html == cached.current_result.formatted_html:
            await self._edit_reply_markup_only(cached, reply_markup)
            return

        try:
            if cached.edit_mode == "caption":
                await self._bot.edit_message_caption(
                    chat_id=cached.chat_id,
                    message_id=cached.message_id,
                    caption=new_result.formatted_html,
                    reply_markup=reply_markup,
                )
                return

            await self._bot.edit_message_text(
                chat_id=cached.chat_id,
                message_id=cached.message_id,
                text=new_result.formatted_html,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def _edit_reply_markup_only(
        self,
        cached: CachedDraft,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=cached.chat_id,
                message_id=cached.message_id,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def _clear_reply_markup(self, cached: CachedDraft) -> None:
        await self._edit_reply_markup_only(cached, None)

    def _append_jsonl(self, path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
