from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.reply_target import ReplyTarget
from app.bot.sender import Sender
from app.config import Settings
from app.db.models import Base
from app.db.session import make_engine, make_sessionmaker
from app.delivery import cache
from app.delivery.cache import StoredPart
from app.delivery.captions import build_caption
from app.delivery.egress import over_budget, record_url_send, url_send_allowed
from app.delivery.finalize import finalize, put_part, set_meta
from app.delivery.pending import PendingDelivery, add_waiter
from app.delivery.send import deliver_parts
from app.relay.parsing import choose_button, classify_message, media_plausible

FORUM = -1002000000000
STORAGE = -1001000000000


def part(kind="video", fid="F1", msg=1):
    return StoredPart(kind, fid, f"u{fid}", 100, STORAGE, msg)


def fake_sender():
    bot = MagicMock()
    for name in (
        "send_message",
        "send_photo",
        "send_video",
        "send_audio",
        "send_document",
        "send_media_group",
        "copy_message",
        "delete_message",
    ):
        setattr(bot, name, AsyncMock())
    return Sender(bot), bot


# --- captions ---------------------------------------------------------------


def test_caption_has_source_and_bot_and_escapes():
    text = build_caption("a <b> & c", "https://x.com/p?a=1&b=2", "xSaveAsBot")
    assert text.startswith("a &lt;b&gt; &amp; c")
    assert 'href="https://x.com/p?a=1&amp;b=2"' in text and text.endswith("@xSaveAsBot")


def test_caption_never_exceeds_limit():
    text = build_caption("<" * 5000, "https://example.com/" + "a" * 200, "bot")
    assert len(text) <= 1024 and text.endswith("@bot")


def test_caption_without_original():
    assert build_caption(None, None, "bot") == "@bot"
    assert build_caption("hi", None, None) == "hi"


# --- sending ---------------------------------------------------------------


async def test_album_chunks_of_ten_with_caption_on_first():
    sender, bot = fake_sender()
    target = ReplyTarget(chat_id=FORUM, message_thread_id=7, reply_to_message_id=3)
    parts = [part("photo", f"P{i}", i) for i in range(12)]
    await deliver_parts(sender, target, parts, "cap")
    calls = bot.send_media_group.call_args_list
    assert [len(c.kwargs["media"]) for c in calls] == [10, 2]
    assert calls[0].kwargs["media"][0].caption == "cap"
    assert (
        calls[0].kwargs["media"][1].caption is None and calls[1].kwargs["media"][0].caption is None
    )
    assert all(c.kwargs["message_thread_id"] == 7 for c in calls)


async def test_single_video_and_audio_use_right_methods():
    sender, bot = fake_sender()
    target = ReplyTarget(chat_id=5)
    await deliver_parts(sender, target, [part("video")], "c")
    await deliver_parts(sender, target, [part("audio", "A")], "c")
    assert bot.send_video.call_args.kwargs["video"] == "F1"
    assert bot.send_audio.call_args.kwargs["audio"] == "A"


async def test_mixed_album_is_sent_one_by_one():
    sender, bot = fake_sender()
    await deliver_parts(
        ReplyTarget(chat_id=5) and sender,
        ReplyTarget(chat_id=5),
        [part("video"), part("document", "D")],
        "c",
    )
    assert bot.send_media_group.call_count == 0
    assert bot.send_video.call_args.kwargs["caption"] == "c"
    assert bot.send_document.call_args.kwargs["caption"] is None


# --- finalize / cache -------------------------------------------------------


@pytest.fixture
async def env():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(_env_file=None, bot_token="1:T", storage_channel_default=STORAGE)
    yield make_sessionmaker(engine), fakeredis.FakeAsyncRedis(), settings
    await engine.dispose()


async def test_album_assembled_from_out_of_order_parts_and_delivered_per_topic(env):
    sm, redis, settings = env
    sender, bot = fake_sender()
    key = "ig:ABC"
    await set_meta(
        redis, key, {"platform": "instagram", "caption": "hello", "source_url": "https://i/ABC"}
    )
    a = PendingDelivery(
        ReplyTarget(chat_id=FORUM, message_thread_id=5, reply_to_message_id=1), "uz", 1, 11
    )
    b = PendingDelivery(
        ReplyTarget(chat_id=FORUM, message_thread_id=9, reply_to_message_id=2), "ru", 2, 12
    )
    assert await add_waiter(redis, key, a) and not await add_waiter(redis, key, b)

    assert await put_part(redis, key, 2, 3, part("photo", "P2", 2)) is None
    assert await put_part(redis, key, 3, 3, part("video", "P3", 3)) is None
    parts = await put_part(redis, key, 1, 3, part("photo", "P1", 1))
    assert [p.file_id for p in parts] == ["P1", "P2", "P3"]
    # Exactly once: a duplicate last part must not trigger a second finalize
    assert await put_part(redis, key, 1, 3, part("photo", "P1", 1)) is None

    async with sm() as session:
        await finalize(
            redis=redis,
            session=session,
            sender=sender,
            settings=settings,
            bot_username="xBot",
            key=key,
            parts=parts,
        )
    groups = bot.send_media_group.call_args_list
    assert sorted(c.kwargs["message_thread_id"] for c in groups) == [5, 9]
    assert groups[0].kwargs["media"][0].caption.startswith("hello")
    # status messages cleaned up
    assert {c.kwargs["message_id"] for c in bot.delete_message.call_args_list} == {11, 12}

    async with sm() as session:
        cached = await cache.get_entry(session, key)
        await session.commit()
    assert cached is not None and [p.file_id for p in cached.parts] == ["P1", "P2", "P3"]
    assert cached.caption.endswith("@xBot")


async def test_cache_miss_and_hit_counter(env):
    sm, _, _ = env
    async with sm() as session:
        assert await cache.get_entry(session, "nope") is None
        await cache.save_entry(session, "k", "youtube", [part()], "cap")
        assert (await cache.get_entry(session, "k")).caption == "cap"
        assert (await cache.get_entry(session, "k")) is not None
        await session.commit()
    from sqlalchemy import select

    from app.db.models import MediaCache

    async with sm() as session:
        assert await session.scalar(select(MediaCache.hits).where(MediaCache.key == "k")) == 2


# --- egress ------------------------------------------------------------------


async def test_budget_and_url_send_autodisable(env):
    _, redis, settings = env
    settings.egress_daily_budget_gb = 1
    assert not await over_budget(redis, settings, 10)
    assert await over_budget(redis, settings, 2 * 1024**3)
    for _ in range(3):
        await record_url_send(redis, "tiktok", True)
    for _ in range(9):
        await record_url_send(redis, "tiktok", False)
    assert not await url_send_allowed(redis, "tiktok")  # 12 attempts, 75% failed
    assert await url_send_allowed(redis, "pinterest")


# --- relay parsing -------------------------------------------------------------


def msg(text="", media=None, buttons=None, duration=None, size=10):
    file = SimpleNamespace(duration=duration, size=size)
    return SimpleNamespace(message=text, media=media, buttons=buttons, file=file)


class MessageMediaDocument: ...


class MessageMediaWebPage: ...


def test_classify_helper_messages():
    assert classify_message(msg(media=MessageMediaDocument())) == "media"
    assert classify_message(msg("see https://x", media=MessageMediaWebPage())) == "progress"
    assert classify_message(msg("Please subscribe to our channel @spam")) == "junk"
    assert classify_message(msg("Подпишитесь на канал")) == "junk"
    assert classify_message(msg("Ошибка: видео не найдено")) == "error"
    assert classify_message(msg("This video is private")) == "error"
    assert classify_message(msg("Choose quality", buttons=[[1]])) == "buttons"
    assert classify_message(msg("Processing…")) == "progress"


def button(text, url=None):
    return SimpleNamespace(text=text, url=url)


def test_choose_button_by_variant():
    rows = [
        [button("360p"), button("720p")],
        [button("🎧 MP3"), button("Channel", url="https://t.me/x")],
    ]
    assert choose_button(rows, "720p") == (0, 1)
    assert choose_button(rows, "mp3") == (1, 0)
    assert choose_button(rows, "best") == (0, 1)  # prefers 720/best-like over first
    assert choose_button([[button("Join", url="https://t.me/x")]], None) is None
    assert choose_button([[button("Foo"), button("Bar")]], None) == (0, 0)


def test_media_plausibility():
    assert media_plausible(msg(duration=100), 100)
    assert media_plausible(msg(duration=118), 100)
    assert not media_plausible(msg(duration=15), 200)  # an ad
    assert media_plausible(msg(duration=15), None)  # nothing to compare with
    assert not media_plausible(msg(size=0), None)


_ = AsyncSession  # keep import used for type clarity in fixtures


# --- wanted media kind (video sites must not accept thumbnails) -------------------


class MessageMediaPhoto: ...


def typed(text="", media=None, buttons=None, mime=None, **attrs):
    m = msg(text, media, buttons)
    m.file = SimpleNamespace(duration=None, size=10, mime_type=mime)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def test_thumbnail_photo_is_not_a_video_result():
    from app.relay.parsing import wanted_kind

    assert wanted_kind("youtube", None) == "video" and wanted_kind("youtube", "mp3") == "audio"
    assert wanted_kind("instagram", None) == "any" and wanted_kind("vimeo", "720p") == "video"

    thumb = typed("Title", MessageMediaPhoto(), None)
    assert classify_message(thumb, "video") == "progress"
    picker = typed("Choose quality", MessageMediaPhoto(), [[button("720p")]])
    assert classify_message(picker, "video") == "buttons"
    assert classify_message(picker, "any") == "buttons"  # photo + buttons is always a prompt
    assert classify_message(thumb, "any") == "media"  # an Instagram photo post is a result


def test_video_and_audio_documents_match():
    video = typed("", MessageMediaDocument(), None, mime="video/mp4")
    audio = typed("", MessageMediaDocument(), None, mime="audio/mpeg")
    assert classify_message(video, "video") == "media"
    assert classify_message(audio, "video") == "progress"  # wrong kind is ignored
    assert classify_message(audio, "audio") == "media"
    assert classify_message(video, "audio") == "progress"
    video_with_buttons = typed("", MessageMediaDocument(), [[button("More")]], mime="video/mp4")
    assert classify_message(video_with_buttons, "video") == "media"
