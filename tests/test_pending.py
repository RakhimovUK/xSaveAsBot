import fakeredis

from app.bot.reply_target import ReplyTarget
from app.delivery.pending import PendingDelivery, add_waiter, pop_waiters


async def test_waiters_from_different_topics_each_keep_their_target():
    redis = fakeredis.FakeAsyncRedis()
    a = PendingDelivery(ReplyTarget(chat_id=-100, message_thread_id=5, reply_to_message_id=1), "uz")
    b = PendingDelivery(ReplyTarget(chat_id=-100, message_thread_id=9, reply_to_message_id=2), "ru")
    c = PendingDelivery(ReplyTarget(chat_id=42, reply_to_message_id=3), "en", user_id=42)

    assert await add_waiter(redis, "yt:abc:720p", a) is True  # first starts the job
    assert await add_waiter(redis, "yt:abc:720p", b) is False  # dedup
    assert await add_waiter(redis, "yt:abc:720p", c) is False

    assert await pop_waiters(redis, "yt:abc:720p") == [a, b, c]
    assert await pop_waiters(redis, "yt:abc:720p") == []
