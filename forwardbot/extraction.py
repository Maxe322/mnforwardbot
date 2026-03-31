from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import Message

from forwardbot.models import IncomingPost, MediaItem, MediaKind, UnsupportedMessageError


def message_to_incoming_post(message: Message) -> IncomingPost:
    media_items = _extract_media_items(message)
    text = _extract_text(message)

    if not text:
        raise UnsupportedMessageError("Der Beitrag enthält keinen Text oder keine Caption zum Umschreiben.")

    return IncomingPost(
        sender_user_id=_require_sender_user_id(message),
        chat_id=message.chat.id,
        source_text=text,
        media_items=tuple(media_items),
        media_group_id=message.media_group_id,
        source_chat_title=_extract_source_title(message),
        source_message_id=message.message_id,
        forwarded=message.forward_origin is not None,
    )


def media_group_to_incoming_post(messages: Sequence[Message]) -> IncomingPost:
    if not messages:
        raise UnsupportedMessageError("Leere Media-Group kann nicht verarbeitet werden.")

    ordered_messages = sorted(messages, key=lambda item: item.message_id)
    first_message = ordered_messages[0]
    media_items: list[MediaItem] = []

    for message in ordered_messages:
        items = _extract_media_items(message)
        if len(items) != 1:
            raise UnsupportedMessageError("Media-Groups dürfen nur Fotos und Videos enthalten.")
        media_items.extend(items)

    source_text = ""
    for message in ordered_messages:
        source_text = _extract_text(message)
        if source_text:
            break

    if not source_text:
        raise UnsupportedMessageError("Die Media-Group enthält keine Caption zum Umschreiben.")

    return IncomingPost(
        sender_user_id=_require_sender_user_id(first_message),
        chat_id=first_message.chat.id,
        source_text=source_text,
        media_items=tuple(media_items),
        media_group_id=first_message.media_group_id,
        source_chat_title=_extract_source_title(first_message),
        source_message_id=first_message.message_id,
        forwarded=first_message.forward_origin is not None,
    )


def _extract_media_items(message: Message) -> list[MediaItem]:
    if message.photo:
        return [
            MediaItem(
                kind=MediaKind.PHOTO,
                file_id=message.photo[-1].file_id,
                has_spoiler=bool(getattr(message, "has_media_spoiler", False)),
            )
        ]
    if message.video:
        return [
            MediaItem(
                kind=MediaKind.VIDEO,
                file_id=message.video.file_id,
                has_spoiler=bool(getattr(message, "has_media_spoiler", False)),
                supports_streaming=bool(getattr(message.video, "supports_streaming", False)),
            )
        ]

    unsupported_fields = (
        "animation",
        "audio",
        "document",
        "sticker",
        "voice",
        "video_note",
        "contact",
        "location",
        "poll",
    )
    for field_name in unsupported_fields:
        if getattr(message, field_name, None) is not None:
            raise UnsupportedMessageError(
                "Dieser Nachrichtentyp wird noch nicht unterstützt. Erlaubt sind Text, Foto, Video und Foto/Video-Alben."
            )

    return []


def _extract_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _require_sender_user_id(message: Message) -> int:
    if message.from_user is None:
        raise UnsupportedMessageError("Die Nachricht hat keinen Telegram-Nutzer als Absender.")
    return message.from_user.id


def _extract_source_title(message: Message) -> str | None:
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None

    sender_chat = getattr(origin, "sender_chat", None)
    if sender_chat is not None and getattr(sender_chat, "title", None):
        return sender_chat.title

    chat = getattr(origin, "chat", None)
    if chat is not None and getattr(chat, "title", None):
        return chat.title

    sender_user = getattr(origin, "sender_user", None)
    if sender_user is not None:
        full_name = " ".join(part for part in [sender_user.first_name, sender_user.last_name] if part)
        return full_name or getattr(sender_user, "username", None)

    return None
