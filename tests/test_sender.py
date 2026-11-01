from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.bot.reply_target import ReplyTarget
from app.bot.sender import Sender


def make_sender():
    bot = MagicMock()
    for name in (
        "send_message",
        "send_photo",
        "send_media_group",
        "copy_message",
        "send_chat_action",
    ):
        setattr(bot, name, AsyncMock(return_value="ok"))
    return Sender(bot), bot


def thread_error():
    return TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"), message="Bad Request: message thread not found"
    )


async def test_topic_target_passes_thread_and_reply():
    sender, bot = make_sender()
    await sender.text(ReplyTarget(chat_id=-100, message_thread_id=55, reply_to_message_id=9), "hi")
    kw = bot.send_message.call_args.kwargs
    assert kw["chat_id"] == -100
    assert kw["message_thread_id"] == 55
    assert kw["reply_parameters"].message_id == 9
    assert kw["reply_parameters"].allow_sending_without_reply is True


async def test_no_thread_key_when_none():
    sender, bot = make_sender()
    await sender.photo(ReplyTarget(chat_id=5, reply_to_message_id=1), "file_id")
    assert "message_thread_id" not in bot.send_photo.call_args.kwargs


async def test_media_group_and_copy_get_thread():
    sender, bot = make_sender()
    target = ReplyTarget(chat_id=-100, message_thread_id=7, reply_to_message_id=1)
    await sender.media_group(target, [])
    await sender.copy(target, from_chat_id=-1009, message_id=3)
    assert bot.send_media_group.call_args.kwargs["message_thread_id"] == 7
    assert bot.copy_message.call_args.kwargs["message_thread_id"] == 7


async def test_chat_action_has_thread_but_no_reply():
    sender, bot = make_sender()
    await sender.chat_action(
        ReplyTarget(chat_id=-100, message_thread_id=7, reply_to_message_id=1), "upload_video"
    )
    kw = bot.send_chat_action.call_args.kwargs
    assert kw["message_thread_id"] == 7
    assert "reply_parameters" not in kw


async def test_thread_error_raises_without_fallback():
    sender, bot = make_sender()
    bot.send_message.side_effect = thread_error()
    with pytest.raises(TelegramBadRequest):
        await sender.text(ReplyTarget(chat_id=-100, message_thread_id=55), "hi")
    assert bot.send_message.call_count == 1  # never silently posts to General


async def test_thread_error_falls_back_when_enabled():
    sender, bot = make_sender()
    bot.send_message.side_effect = [thread_error(), "ok"]
    target = ReplyTarget(
        chat_id=-100, message_thread_id=55, reply_to_message_id=3, fallback_without_thread=True
    )
    assert await sender.text(target, "hi") == "ok"
    retry = bot.send_message.call_args_list[1].kwargs
    assert "message_thread_id" not in retry and "reply_parameters" not in retry


async def test_inline_target_cannot_send():
    sender, _ = make_sender()
    with pytest.raises(ValueError):
        await sender.text(ReplyTarget(inline_message_id="AAA"), "hi")
