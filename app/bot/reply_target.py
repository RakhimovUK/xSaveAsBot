"""ReplyTarget: where an answer must go (brief section 2a).

Built once from the incoming update and carried through queues / pending deliveries,
so every reply lands in the same chat AND the same forum topic as the request.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from aiogram.types import CallbackQuery, InaccessibleMessage, Message


def _thread_id(message: Message) -> int | None:
    # Only real topic messages carry a usable thread id. In the General topic, in
    # non-forum groups (where reply chains also set message_thread_id) and in plain
    # private chats it must be omitted, or Telegram says "message thread not found".
    if message.is_topic_message:
        return message.message_thread_id
    return None


@dataclass(frozen=True, slots=True)
class ReplyTarget:
    chat_id: int | None = None
    message_thread_id: int | None = None
    reply_to_message_id: int | None = None
    inline_message_id: str | None = None
    # Per-group opt-in: retry without thread id if the topic is closed/deleted
    fallback_without_thread: bool = False

    @classmethod
    def from_message(
        cls, message: Message, *, fallback_without_thread: bool = False
    ) -> ReplyTarget:
        return cls(
            chat_id=message.chat.id,
            message_thread_id=_thread_id(message),
            reply_to_message_id=message.message_id,
            fallback_without_thread=fallback_without_thread,
        )

    @classmethod
    def from_callback(
        cls, callback: CallbackQuery, *, fallback_without_thread: bool = False
    ) -> ReplyTarget:
        """Target for follow-ups of a button press, in the topic of the button's message."""
        msg = callback.message
        if msg is None:
            # Button on an inline-mode message
            return cls(inline_message_id=callback.inline_message_id)
        if isinstance(msg, InaccessibleMessage):
            # Too old to read thread info; reply in the chat root
            return cls(chat_id=msg.chat.id, fallback_without_thread=fallback_without_thread)
        # Keyboard messages reply to the user's original message; answer that one.
        original = msg.reply_to_message
        reply_to = original.message_id if original is not None else msg.message_id
        return cls(
            chat_id=msg.chat.id,
            message_thread_id=_thread_id(msg),
            reply_to_message_id=reply_to,
            fallback_without_thread=fallback_without_thread,
        )

    @classmethod
    def from_inline(cls, inline_message_id: str) -> ReplyTarget:
        return cls(inline_message_id=inline_message_id)

    @property
    def is_inline(self) -> bool:
        return self.inline_message_id is not None and self.chat_id is None

    def without_thread(self) -> ReplyTarget:
        return ReplyTarget(
            chat_id=self.chat_id,
            message_thread_id=None,
            reply_to_message_id=None,
            inline_message_id=self.inline_message_id,
            fallback_without_thread=False,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str | bytes) -> ReplyTarget:
        return cls(**json.loads(raw))
