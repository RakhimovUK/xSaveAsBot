"""channel_post updates from our storage channels: the source of the bot's own file_ids.

Every storage post carries `#key <cache-key> #part i/n`. Parts are collected in Redis;
when the last one arrives the cache is written and all waiting requests (each with its
own chat and forum topic) get the media.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.media_utils import extract_file, parse_key, parse_part
from app.bot.sender import Sender
from app.config import Settings
from app.delivery.cache import StoredPart
from app.delivery.finalize import finalize, put_part

log = logging.getLogger(__name__)

router = Router(name="storage_posts")


class FromStorageChannel(Filter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return message.chat.id in settings.all_storage_channel_ids


@router.channel_post(FromStorageChannel())
async def on_storage_post(
    message: Message,
    sender: Sender,
    arq: ArqRedis,
    session: AsyncSession,
    settings: Settings,
    bot_username: str | None = None,
) -> None:
    stored = extract_file(message)
    key = parse_key(message.caption)
    index, total = parse_part(message.caption)
    log.info(
        "storage post chat=%s msg=%s key=%s part=%s/%s kind=%s file_id=%s size=%s",
        message.chat.id,
        message.message_id,
        key,
        index,
        total,
        stored.kind if stored else None,
        stored.file_id if stored else None,
        stored.size if stored else None,
    )
    if stored is None or key is None:
        return
    part = StoredPart(
        stored.kind,
        stored.file_id,
        stored.file_unique_id,
        stored.size,
        message.chat.id,
        message.message_id,
    )
    parts = await put_part(arq, key, index, total, part)
    if parts is None:
        return
    await finalize(
        redis=arq,
        session=session,
        sender=sender,
        settings=settings,
        bot_username=bot_username,
        key=key,
        parts=parts,
    )
