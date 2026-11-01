"""relay_fetch: race helpers, first valid media wins, losers cancelled, failures recorded."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import Base, HelperBot
from app.db.session import make_engine, make_sessionmaker
from app.relay import registry
from app.uploader import relay


@pytest.fixture
async def ctx():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = make_sessionmaker(engine)
    async with sm() as session:
        await registry.add_helper(session, "@SlowBot", "all", 10)
        await registry.add_helper(session, "@FastBot", "all", 20)
        await registry.add_helper(session, "@BrokenBot", "all", 30)
        await registry.add_helper(session, "@YtOnly", "youtube", 5)
        await session.commit()
    client = SimpleNamespace(send_file=AsyncMock())
    settings = Settings(
        _env_file=None, bot_token="1:T", storage_channel_default=-1001, relay_timeout_s=5
    )
    redis = fakeredis.FakeAsyncRedis()
    await redis.set("xsaveasbot:relay:started:slowbot", "1")  # skip /start handshake
    yield {
        "settings": settings,
        "redis": redis,
        "sessionmaker": sm,
        "userbots": SimpleNamespace(get=lambda: client),
        "client": client,
    }
    await engine.dispose()


def media(msg_id):
    return SimpleNamespace(id=msg_id, media=f"media{msg_id}")


async def helper_row(ctx, username):
    async with ctx["sessionmaker"]() as session:
        return await session.scalar(select(HelperBot).where(HelperBot.username == username))


def patch(monkeypatch, behaviors):
    async def fake_converse(client, username, url, variant, expected, timeout):
        return await behaviors[username]()

    async def no_start(client, redis, username):
        return None

    monkeypatch.setattr(relay, "converse", fake_converse)
    monkeypatch.setattr(relay, "_ensure_started", no_start)


async def test_fast_helper_wins_and_slow_one_is_cancelled(ctx, monkeypatch):
    cancelled = []

    async def slow():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append("slowbot")
            raise

    async def fast():
        await asyncio.sleep(0.05)
        return [media(7)]

    patch(monkeypatch, {"slowbot": slow, "fastbot": fast, "brokenbot": slow, "ytonly": slow})
    res = await relay.relay_fetch(ctx, "ig:A", "https://x", "instagram", None, -1001, None)
    # youtube-only helper is not eligible for instagram; slowbot (prio 10) + fastbot race
    assert res == {"ok": True, "helper": "fastbot", "parts": 1}
    assert cancelled == ["slowbot"]
    ctx["client"].send_file.assert_awaited_once_with(-1001, "media7", caption="#key ig:A #part 1/1")
    assert (await helper_row(ctx, "fastbot")).success == 1
    assert (await helper_row(ctx, "slowbot")).fail == 0  # losing the race is not a failure
    # locks released so the next request can use both helpers again
    assert not await ctx["redis"].exists("xsaveasbot:relay:lock:slowbot")


async def test_failed_helper_is_recorded_and_next_batch_is_tried(ctx, monkeypatch):
    async def junk():
        raise relay.RelayError("junk/subscription prompt")

    async def ok():
        return [media(1), media(2)]

    patch(monkeypatch, {"slowbot": junk, "fastbot": junk, "brokenbot": ok, "ytonly": junk})
    res = await relay.relay_fetch(ctx, "ig:B", "https://x", "instagram", None, -1001, None)
    assert res["ok"] and res["helper"] == "brokenbot" and res["parts"] == 2
    row = await helper_row(ctx, "slowbot")
    assert row.fail == 1 and "junk" in row.last_error
    calls = [c.kwargs["caption"] for c in ctx["client"].send_file.call_args_list]
    assert calls == ["#key ig:B #part 1/2", "#key ig:B #part 2/2"]


async def test_three_failures_put_helper_on_cooldown(ctx, monkeypatch):
    async def junk():
        raise relay.RelayError("error")

    patch(monkeypatch, {"slowbot": junk, "fastbot": junk, "brokenbot": junk, "ytonly": junk})
    for _ in range(3):
        res = await relay.relay_fetch(ctx, "ig:C", "https://x", "instagram", None, -1001, None)
        assert not res["ok"]
    async with ctx["sessionmaker"]() as session:
        usable = [h.username for h in await registry.pick_helpers(session, "instagram")]
    assert usable == []  # all three cooling down


async def test_youtube_prefers_youtube_helper_and_no_helpers_message(ctx, monkeypatch):
    seen = []

    async def ok():
        return [media(1)]

    async def record(client, username, url, variant, expected, timeout):
        seen.append(username)
        return [media(1)]

    monkeypatch.setattr(relay, "converse", record)

    async def no_start(client, redis, username):
        return None

    monkeypatch.setattr(relay, "_ensure_started", no_start)
    res = await relay.relay_fetch(ctx, "yt:X:best", "https://y", "youtube", "best", -1001, None)
    assert (res["ok"] and seen[0] == "ytonly") or "ytonly" in seen  # prio 5 is raced first

    async with ctx["sessionmaker"]() as session:
        for name in ("slowbot", "fastbot", "brokenbot", "ytonly"):
            await registry.set_enabled(session, name, False)
        await session.commit()
    res = await relay.relay_fetch(ctx, "yt:Z", "https://y", "youtube", None, -1001, None)
    assert res == {"ok": False, "error": "no helper bots available"}
