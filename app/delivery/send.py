"""Send stored media (by file_id) to a ReplyTarget: single files and albums."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto, InputMediaVideo

from app.bot.reply_target import ReplyTarget
from app.bot.sender import Sender
from app.delivery.cache import StoredPart

log = logging.getLogger(__name__)

ALBUM_SIZE = 10
GROUPABLE = {"photo", "video"}


async def _send_one(
    sender: Sender, target: ReplyTarget, part: StoredPart, caption: str | None
) -> None:
    try:
        if part.kind == "photo":
            await sender.photo(target, part.file_id, caption=caption)
        elif part.kind == "video":
            await sender.video(target, part.file_id, caption=caption, supports_streaming=True)
        elif part.kind == "audio":
            await sender.audio(target, part.file_id, caption=caption)
        elif part.kind == "animation":
            await sender.animation(target, part.file_id, caption=caption)
        else:
            await sender.document(target, part.file_id, caption=caption)
    except TelegramBadRequest as exc:
        # file_id unusable (e.g. bot changed): fall back to copying from the storage channel
        if "thread" in exc.message.lower():
            raise
        log.warning("file_id send failed (%s); copying from storage", exc.message)
        await sender.copy(target, part.chat_id, part.message_id, caption=caption)


def _media(part: StoredPart, caption: str | None):
    cls = InputMediaPhoto if part.kind == "photo" else InputMediaVideo
    return cls(media=part.file_id, caption=caption, parse_mode="HTML")


async def deliver_parts(
    sender: Sender, target: ReplyTarget, parts: list[StoredPart], caption: str | None
) -> None:
    if len(parts) == 1:
        await _send_one(sender, target, parts[0], caption)
        return
    if all(p.kind in GROUPABLE for p in parts):
        for start in range(0, len(parts), ALBUM_SIZE):
            chunk = parts[start : start + ALBUM_SIZE]
            media = [
                _media(p, caption if start == 0 and i == 0 else None) for i, p in enumerate(chunk)
            ]
            if len(media) == 1:  # media group needs 2+ items
                await _send_one(sender, target, chunk[0], caption if start == 0 else None)
            else:
                await sender.media_group(target, media)
        return
    for i, part in enumerate(parts):
        await _send_one(sender, target, part, caption if i == 0 else None)
