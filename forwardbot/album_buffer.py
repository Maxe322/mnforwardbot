from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram.types import Message

logger = logging.getLogger(__name__)

AlbumCallback = Callable[[list[Message]], Awaitable[None]]


class AlbumBuffer:
    def __init__(self, delay_seconds: float, callback: AlbumCallback) -> None:
        self._delay_seconds = delay_seconds
        self._callback = callback
        self._messages: dict[str, list[Message]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def add(self, message: Message) -> None:
        if not message.media_group_id:
            raise ValueError("AlbumBuffer.add requires message.media_group_id to be set.")

        key = self._key(message.chat.id, message.media_group_id)
        async with self._lock:
            bucket = self._messages.setdefault(key, [])
            if not any(existing.message_id == message.message_id for existing in bucket):
                bucket.append(message)
                bucket.sort(key=lambda item: item.message_id)

            task = self._tasks.get(key)
            if task is not None:
                task.cancel()

            self._tasks[key] = asyncio.create_task(self._flush_after_delay(key))

    async def close(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            self._messages.clear()

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _flush_after_delay(self, key: str) -> None:
        try:
            await asyncio.sleep(self._delay_seconds)
        except asyncio.CancelledError:
            return

        async with self._lock:
            messages = self._messages.pop(key, [])
            self._tasks.pop(key, None)

        if not messages:
            return

        try:
            await self._callback(messages)
        except Exception:
            logger.exception("Album processing failed for key %s.", key)

    @staticmethod
    def _key(chat_id: int, media_group_id: str) -> str:
        return f"{chat_id}:{media_group_id}"

