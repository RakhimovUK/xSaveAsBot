"""channel_post updates from our storage channels: the source of the bot's own file_ids."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import Message
from arq import ArqRedis

from app.bot.media_utils import StoredFile, extract_file, parse_key
from app.bot.sender import Sender
from app.config import Settings
from app.delivery.pending import pop_waiters
from app.i18n import gettext

log = logging.getLogger(__name__)

router = Router(name="storage_posts")


class FromStorageChannel(Filter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return message.chat.id in settings.all_storage_channel_ids


async def _deliver_file(sender: Sender, target, stored: StoredFile, caption: str) -> None:
    send = {
        "photo": sender.photo,
        "video": sender.video,
        "animation": sender.animation,
        "audio": sender.audio,
    }.get(stored.kind, sender.document)
    await send(target, stored.file_id, caption=caption)


@router.channel_post(FromStorageChannel())
async def on_storage_post(message: Message, sender: Sender, arq: ArqRedis) -> None:
    stored = extract_file(message)
    key = parse_key(message.caption)
    log.info(
        "storage post chat=%s msg=%s key=%s kind=%s file_id=%s size=%s",
        message.chat.id,
        message.message_id,
        key,
        stored.kind if stored else None,
        stored.file_id if stored else None,
        stored.size if stored else None,
    )
    if stored is None or key is None:
        return
    # Phase 2 writes media_cache here. Phase 1: deliver to whoever is waiting.
    for waiter in await pop_waiters(arq, key):
        try:
            await _deliver_file(
                sender,
                waiter.target,
                stored,
                gettext(waiter.lang, "testupload-done", file_id=stored.file_id),
            )
        except Exception:
            log.exception("delivery failed key=%s target=%s", key, waiter.target)
