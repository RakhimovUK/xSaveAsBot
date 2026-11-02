"""Delivery ladder scenarios with fake extractors, fake uploader and fake Bot API."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
from sqlalchemy import select

from app.bot.reply_target import ReplyTarget
from app.bot.sender import Sender
from app.config import Settings
from app.db.models import Base, Download
from app.db.session import make_engine, make_sessionmaker
from app.delivery import ladder as ladder_mod
from app.delivery.cache import StoredPart
from app.delivery.finalize import mark_done
from app.delivery.jobs import LinkJob
from app.delivery.ladder import Processor
from app.extractors.base import MediaInfo, MediaItem
from app.extractors.errors import BotCheckError, NotFoundError

STORAGE = -1001000000000
TARGET = ReplyTarget(chat_id=-1002000000000, message_thread_id=7, reply_to_message_id=50)


def storage_message(kind, file_id, message_id=500):
    base = {
        "chat": SimpleNamespace(id=STORAGE),
        "message_id": message_id,
        "photo": None,
        "video": None,
        "animation": None,
        "audio": None,
        "voice": None,
        "video_note": None,
        "document": None,
    }
    obj = SimpleNamespace(file_id=file_id, file_unique_id="u" + file_id, file_size=1000)
    if kind == "photo":
        base["photo"] = [obj]
    else:
        base[kind] = obj
    return SimpleNamespace(**base)


class FakeJob:
    def __init__(self, result):
        self._result = result

    async def result(self, timeout=None):
        return self._result


class Rig:
    def __init__(self, sm, redis, settings):
        self.bot = MagicMock()
        for name in (
            "send_message",
            "send_photo",
            "send_video",
            "send_media_group",
            "delete_message",
            "edit_message_text",
            "send_audio",
            "send_document",
            "send_animation",
            "copy_message",
        ):
            setattr(self.bot, name, AsyncMock())
        self.bot.send_video.side_effect = lambda **kw: storage_message("video", "VID")
        self.bot.send_photo.side_effect = lambda **kw: storage_message("photo", "PIC")
        self.redis = redis
        self.enqueued = []
        self.uploader_result = {"ok": True}
        self.mark_done_on_enqueue = True

        async def enqueue_job(name, *args, **kwargs):
            self.enqueued.append((name, args))
            if self.mark_done_on_enqueue and name in ("relay_fetch", "upload_files"):
                await mark_done(redis, args[0])
            return FakeJob(self.uploader_result)

        redis.enqueue_job = enqueue_job
        self.processor = Processor(
            settings=settings,
            redis=redis,
            sessionmaker=sm,
            sender=Sender(self.bot),
            bot_username="xBot",
        )

    def job(self, url, variant=None, status=77):
        return LinkJob.create(url, TARGET, "en", 42, status, variant)

    def texts(self):
        return [c.kwargs.get("text") for c in self.bot.edit_message_text.call_args_list]


@pytest.fixture
async def rig(monkeypatch, tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(
        _env_file=None, bot_token="1:T", storage_channel_default=STORAGE, jobs_dir=str(tmp_path)
    )
    r = Rig(make_sessionmaker(engine), fakeredis.FakeAsyncRedis(), settings)
    r.settings, r.sm = settings, make_sessionmaker(engine)
    monkeypatch.setattr(ladder_mod, "fetch_oembed", AsyncMock(return_value=None))  # no network
    yield r
    await engine.dispose()


def reel(url="https://cdn/x.mp4", size=2_000_000, duration=10.0):
    return MediaInfo(
        platform="instagram",
        key="ig:AAA",
        source_url="https://www.instagram.com/reel/AAA/",
        caption="nice reel",
        duration=duration,
        items=[MediaItem("video", url=url, size=size, duration=duration)],
    )


async def downloads(rig):
    async with rig.sm() as session:
        return list((await session.scalars(select(Download))).all())


async def test_small_instagram_reel_goes_url_send_zero_egress(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(return_value=reel()))
    await rig.processor.run(rig.job("https://www.instagram.com/reel/AAA/?igsh=1"))
    kw = rig.bot.send_video.call_args_list[0].kwargs  # first call: post to storage channel
    assert kw["chat_id"] == STORAGE and kw["video"] == "https://cdn/x.mp4"
    assert kw["caption"] == "#key ig:AAA #part 1/1"
    # delivered to the requester's own topic, with a fresh caption
    final = rig.bot.send_video.call_args_list[-1].kwargs
    assert final["chat_id"] == TARGET.chat_id and final["message_thread_id"] == 7
    assert final["video"] == "VID" and "nice reel" in final["caption"]
    assert rig.enqueued == []  # userbot not involved: zero egress
    [row] = await downloads(rig)
    assert (row.method, row.status, row.bytes_egress, row.platform) == ("url", "ok", 0, "instagram")


async def test_second_request_is_served_from_cache(rig, monkeypatch):
    probe = AsyncMock(return_value=reel())
    monkeypatch.setattr(ladder_mod.service, "probe", probe)
    await rig.processor.run(rig.job("https://www.instagram.com/reel/AAA/"))
    await rig.processor.run(rig.job("https://instagram.com/reel/AAA/?utm=1", status=78))
    assert probe.call_count == 1
    assert [r.method for r in await downloads(rig)] == ["url", "cache"]


async def test_url_send_failure_falls_through_to_self_download(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(return_value=reel()))
    rig.bot.send_video.side_effect = RuntimeError("telegram cannot fetch url")
    fetched = AsyncMock(return_value=[SimpleNamespace(size=2_000_000, **{})])
    monkeypatch.setattr(ladder_mod.service, "fetch_files", fetched)
    monkeypatch.setattr(ladder_mod, "asdict", lambda f: {"path": "p"})
    await rig.processor.run(rig.job("https://www.instagram.com/reel/AAA/"))
    assert [n for n, _ in rig.enqueued] == ["upload_files"]
    [row] = await downloads(rig)
    assert (row.method, row.bytes_egress) == ("self", 2_000_000)


async def test_youtube_blocked_uses_relay_with_best_variant(rig, monkeypatch):
    monkeypatch.setattr(
        ladder_mod.service, "probe", AsyncMock(side_effect=BotCheckError("Sign in to confirm"))
    )
    await rig.processor.run(rig.job("https://youtu.be/dQw4w9WgXcQ"))
    kw = rig.bot.edit_message_text.call_args.kwargs
    buttons = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
    assert buttons == ["yv:dQw4w9WgXcQ:best", "yv:dQw4w9WgXcQ:mp3"]
    assert not rig.enqueued
    await rig.processor.run(rig.job("https://youtu.be/dQw4w9WgXcQ", "best"))
    name, args = rig.enqueued[0]
    assert name == "relay_fetch"
    assert args[0] == "yt:dQw4w9WgXcQ:best" and args[2] == "youtube" and args[3] == "best"
    row = (await downloads(rig))[-1]
    assert (row.method, row.status) == ("relay", "ok")


async def test_youtube_picker_when_probe_works(rig, monkeypatch):
    from app.extractors.base import FormatOption

    info = MediaInfo(
        platform="youtube",
        key="yt:dQw4w9WgXcQ",
        source_url="u",
        title="Song <3",
        formats=[FormatOption("360p", 360, 10_000_000), FormatOption("720p", 720, None)],
    )
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(return_value=info))
    await rig.processor.run(rig.job("https://youtu.be/dQw4w9WgXcQ"))
    kw = rig.bot.edit_message_text.call_args.kwargs
    buttons = [b for row in kw["reply_markup"].inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == [
        "yv:dQw4w9WgXcQ:360p",
        "yv:dQw4w9WgXcQ:720p",
        "yv:dQw4w9WgXcQ:mp3",
    ]
    assert "10 MB" in buttons[0].text and "Song &lt;3" in kw["text"]
    assert rig.enqueued == []


async def test_private_post_is_reported_not_relayed(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(side_effect=NotFoundError("404")))
    await rig.processor.run(rig.job("https://www.instagram.com/reel/GONE/"))
    assert rig.enqueued == []
    assert "not found" in rig.texts()[-1].lower()
    [row] = await downloads(rig)
    assert (row.status, row.error_class) == ("error", "notfound")


async def test_relay_failure_reports_unavailable_to_every_waiter(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(side_effect=BotCheckError("bot")))
    rig.uploader_result = {"ok": False, "error": "no helper bots available"}
    await rig.processor.run(rig.job("https://youtu.be/dQw4w9WgXcQ", "best"))
    assert "temporarily unavailable" in rig.texts()[-1]


async def test_unsupported_and_disabled(rig, monkeypatch):
    await rig.processor.run(rig.job("https://example.com/x"))
    assert "not supported" in rig.texts()[-1]
    rig.settings.platforms_enabled = ["youtube"]
    await rig.processor.run(rig.job("https://www.instagram.com/reel/AAA/"))
    assert "disabled" in rig.texts()[-1]


async def test_too_long_video_rejected(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(return_value=reel(duration=99999)))
    await rig.processor.run(rig.job("https://www.instagram.com/reel/AAA/"))
    assert "too long" in rig.texts()[-1]


async def test_storage_post_never_arriving_gives_error(rig, monkeypatch):
    monkeypatch.setattr(ladder_mod.service, "probe", AsyncMock(side_effect=BotCheckError("bot")))
    rig.mark_done_on_enqueue = False
    monkeypatch.setattr(Processor, "_wait_done", _fast_wait_done)
    await rig.processor.run(rig.job("https://youtu.be/dQw4w9WgXcQ", "best"))
    assert "couldn't be delivered" in rig.texts()[-1]


async def _fast_wait_done(self, key, seconds=0.2):
    from app.extractors.errors import ExtractError

    raise ExtractError("never", code="nostorage")


_ = StoredPart
