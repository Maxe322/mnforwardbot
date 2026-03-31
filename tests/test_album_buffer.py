from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from forwardbot.album_buffer import AlbumBuffer


@dataclass
class _FakeChat:
    id: int


@dataclass
class _FakeMessage:
    chat: _FakeChat
    media_group_id: str
    message_id: int


@pytest.mark.asyncio
async def test_album_buffer_debounces_and_flushes_once() -> None:
    flushed: list[list[int]] = []

    async def callback(messages: list[_FakeMessage]) -> None:
        flushed.append([message.message_id for message in messages])

    buffer = AlbumBuffer(delay_seconds=0.02, callback=callback)

    try:
        await buffer.add(_FakeMessage(chat=_FakeChat(id=1), media_group_id="grp", message_id=2))
        await buffer.add(_FakeMessage(chat=_FakeChat(id=1), media_group_id="grp", message_id=1))
        await asyncio.sleep(0.06)
    finally:
        await buffer.close()

    assert flushed == [[1, 2]]
