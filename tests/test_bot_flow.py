"""Feed real updates through the dispatcher (DI, middleware, routers) with a fake Bot API."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
from aiogram import Bot
from aiogram.types import Update

from app.bot.main import build_dispatcher
from app.bot.middlewares.context import ContextMiddleware
from app.bot.reply_target import ReplyTarget
from app.bot.sender import Sender
from app.config import Settings
from app.db.models import Base
from app.db.session import make_engine, make_sessionmaker
from app.delivery.pending import PendingDelivery, add_waiter

FORUM = -1002000000000
STORAGE = -1001000000000

# aiogram routers are module singletons and can join only one dispatcher, so build it
# once and swap dependencies per test.
DP = build_dispatcher(echo=True)
MW = ContextMiddleware(None, None)  # type: ignore[arg-type]
DP.update.outer_middleware(MW)


@pytest.fixture
async def env():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(_env_file=None, bot_token="123456:TEST", storage_channel_default=STORAGE)
    api = MagicMock()
    for name in ("send_message", "send_photo"):
        setattr(api, name, AsyncMock())
    redis = fakeredis.FakeAsyncRedis()
    dp = DP
    MW.sessionmaker, MW.settings = make_sessionmaker(engine), settings
    dp["settings"] = settings
    dp["sender"] = Sender(api)
    dp["arq"] = redis
    yield dp, api, redis
    await engine.dispose()


def topic_update(text: str, thread: int | None, message_id: int = 100) -> Update:
    msg = {
        "message_id": message_id,
        "date": datetime.now(UTC),
        "chat": {"id": FORUM, "type": "supergroup", "title": "F", "is_forum": True},
        "from": {"id": 42, "is_bot": False, "first_name": "Ali", "language_code": "ru"},
        "text": text,
    }
    if thread is not None:
        msg["message_thread_id"] = thread
        msg["is_topic_message"] = True
    if text.startswith("/"):
        msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return Update(update_id=1, message=msg)


async def feed(dp, update):
    bot = Bot("123456:TEST")
    try:
        await dp.feed_update(bot, update)
    finally:
        await bot.session.close()


async def test_echo_in_three_topics_and_general(env):
    dp, api, _ = env
    for thread in (None, 11, 22, 33):
        await feed(dp, topic_update("hello", thread, message_id=200 + (thread or 0)))
    calls = [c.kwargs for c in api.send_message.call_args_list]
    assert [c.get("message_thread_id") for c in calls] == [None, 11, 22, 33]
    assert [c["reply_parameters"].message_id for c in calls] == [200, 211, 222, 233]
    assert all("Эхо" in c["text"] for c in calls)  # language from Telegram client (ru)


async def test_start_first_time_shows_language_picker_in_topic(env):
    dp, api, _ = env
    await feed(dp, topic_update("/start", 11))
    kw = api.send_message.call_args.kwargs
    assert kw["message_thread_id"] == 11
    assert kw["reply_markup"].inline_keyboard[0][0].callback_data == "lang:uz"


async def test_storage_post_delivers_to_waiting_topic(env):
    dp, api, redis = env
    target = ReplyTarget(chat_id=FORUM, message_thread_id=22, reply_to_message_id=5)
    await add_waiter(redis, "test:abc", PendingDelivery(target=target, lang="en"))
    post = Update(
        update_id=2,
        channel_post={
            "message_id": 7,
            "date": datetime.now(UTC),
            "chat": {"id": STORAGE, "type": "channel", "title": "storage"},
            "caption": "#key test:abc",
            "photo": [{"file_id": "FID", "file_unique_id": "u", "width": 320, "height": 320}],
        },
    )
    await feed(dp, post)
    kw = api.send_photo.call_args.kwargs
    assert (kw["chat_id"], kw["message_thread_id"], kw["photo"]) == (FORUM, 22, "FID")
    assert "FID" in kw["caption"]


async def test_posts_from_other_channels_are_ignored(env):
    dp, api, redis = env
    await add_waiter(redis, "test:x", PendingDelivery(target=ReplyTarget(chat_id=1), lang="uz"))
    post = Update(
        update_id=3,
        channel_post={
            "message_id": 7,
            "date": datetime.now(UTC),
            "chat": {"id": -1009999, "type": "channel", "title": "other"},
            "caption": "#key test:x",
            "photo": [{"file_id": "FID", "file_unique_id": "u", "width": 1, "height": 1}],
        },
    )
    await feed(dp, post)
    api.send_photo.assert_not_called()
