"""The single outgoing-message gateway (brief section 2a).

Every bot message to users goes through `Sender`, which applies a `ReplyTarget`:
chat id, forum topic (message_thread_id) and reply parameters. Raw `bot.send_*`,
`message.answer()` / `.reply()` etc. are forbidden elsewhere; tests/test_no_raw_sends.py
enforces it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters

from app.bot.reply_target import ReplyTarget

log = logging.getLogger(__name__)

T = TypeVar("T")

_THREAD_ERRORS = ("thread not found", "topic_closed", "topic_deleted", "topic closed")


def is_thread_error(exc: TelegramBadRequest) -> bool:
    text = exc.message.lower()
    return any(marker in text for marker in _THREAD_ERRORS)


class Sender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def _call(
        self,
        target: ReplyTarget,
        method: Callable[..., Awaitable[T]],
        *,
        reply: bool = True,
        **kwargs: Any,
    ) -> T:
        if target.chat_id is None:
            raise ValueError("ReplyTarget has no chat_id (inline targets can only be edited)")
        params: dict[str, Any] = {"chat_id": target.chat_id, **kwargs}
        if target.message_thread_id is not None:
            params["message_thread_id"] = target.message_thread_id
        if reply and target.reply_to_message_id is not None:
            params["reply_parameters"] = ReplyParameters(
                message_id=target.reply_to_message_id, allow_sending_without_reply=True
            )
        try:
            return await method(**params)
        except TelegramBadRequest as exc:
            if target.message_thread_id is None or not is_thread_error(exc):
                raise
            log.warning(
                "Topic unavailable chat=%s thread=%s: %s (fallback=%s)",
                target.chat_id,
                target.message_thread_id,
                exc.message,
                target.fallback_without_thread,
            )
            if not target.fallback_without_thread:
                raise
            params.pop("message_thread_id", None)
            params.pop("reply_parameters", None)
            return await method(**params)

    # --- sends -------------------------------------------------------------

    async def text(
        self,
        target: ReplyTarget,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            target, self.bot.send_message, text=text, reply_markup=reply_markup, **kwargs
        )

    async def photo(self, target: ReplyTarget, photo: Any, **kwargs: Any) -> Message:
        return await self._call(target, self.bot.send_photo, photo=photo, **kwargs)

    async def video(self, target: ReplyTarget, video: Any, **kwargs: Any) -> Message:
        return await self._call(target, self.bot.send_video, video=video, **kwargs)

    async def audio(self, target: ReplyTarget, audio: Any, **kwargs: Any) -> Message:
        return await self._call(target, self.bot.send_audio, audio=audio, **kwargs)

    async def document(self, target: ReplyTarget, document: Any, **kwargs: Any) -> Message:
        return await self._call(target, self.bot.send_document, document=document, **kwargs)

    async def animation(self, target: ReplyTarget, animation: Any, **kwargs: Any) -> Message:
        return await self._call(target, self.bot.send_animation, animation=animation, **kwargs)

    async def media_group(
        self, target: ReplyTarget, media: list[Any], **kwargs: Any
    ) -> list[Message]:
        return await self._call(target, self.bot.send_media_group, media=media, **kwargs)

    async def copy(
        self, target: ReplyTarget, from_chat_id: int, message_id: int, **kwargs: Any
    ) -> Any:
        return await self._call(
            target,
            self.bot.copy_message,
            from_chat_id=from_chat_id,
            message_id=message_id,
            **kwargs,
        )

    async def chat_action(self, target: ReplyTarget, action: str) -> bool:
        if target.chat_id is None:
            return False
        return await self._call(target, self.bot.send_chat_action, reply=False, action=action)

    # --- storage channel + housekeeping (no user-facing reply target) ------------

    async def to_channel(
        self, kind: str, channel_id: int, media: Any, caption: str | None, **kwargs: Any
    ) -> Message:
        """Post media (file_id or URL) to a storage channel; the response carries file_id."""
        method, param = {
            "photo": (self.bot.send_photo, "photo"),
            "video": (self.bot.send_video, "video"),
            "audio": (self.bot.send_audio, "audio"),
            "animation": (self.bot.send_animation, "animation"),
        }.get(kind, (self.bot.send_document, "document"))
        return await method(chat_id=channel_id, caption=caption, **{param: media}, **kwargs)

    async def delete(self, chat_id: int | None, message_id: int | None) -> None:
        if chat_id is None or message_id is None:
            return
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:  # already deleted / no rights: housekeeping only
            log.debug("delete failed chat=%s msg=%s", chat_id, message_id)

    async def edit_status(
        self,
        text: str,
        *,
        chat_id: int | None,
        message_id: int | None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        if chat_id is None or message_id is None:
            return False
        try:
            await self.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
            return True
        except Exception:
            pass
        try:  # a photo message (the quality picker) has a caption, not a text
            await self.bot.edit_message_caption(
                caption=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
            return True
        except Exception:
            log.debug("edit_status failed chat=%s msg=%s", chat_id, message_id)
            return False

    # --- edits (no thread id needed: the message already lives in its topic) ----

    async def edit_text(
        self,
        text: str,
        *,
        chat_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self.bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            reply_markup=reply_markup,
            **kwargs,
        )
