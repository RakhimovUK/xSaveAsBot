"""Helper-bot relay: the userbot asks an external saver bot, then COPIES its media into our
storage channel (no forward header, no bytes through our server).

Depends on third-party bots and can break at any time: it is a fallback, not the core.
One in-flight request per helper (Redis lock); replies are matched by order and time
window, validated against what we probed, and junk (ads, subscribe prompts, errors) is
never delivered.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.bot.media_utils import key_tag
from app.config import Settings
from app.relay import registry
from app.relay.parsing import choose_button, classify_message, media_plausible

log = logging.getLogger(__name__)

POLL_S = 2.0
ALBUM_QUIET_S = 5.0  # wait this long after the last media message for album siblings


class RelayError(Exception):
    pass


async def _acquire(redis: Redis, username: str, wait_s: float) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if await redis.set(f"xsaveasbot:relay:lock:{username}", "1", nx=True, ex=int(wait_s) + 120):
            return True
        await asyncio.sleep(2)
    return False


async def _release(redis: Redis, username: str) -> None:
    await redis.delete(f"xsaveasbot:relay:lock:{username}")


async def converse(
    client: TelegramClient,
    username: str,
    url: str,
    variant: str | None,
    expected_duration: float | None,
    timeout_s: float,
) -> list[Any]:
    """Send `url` to the helper and return its media messages (an album = several)."""
    entity = await client.get_entity(username)
    latest = await client.get_messages(entity, limit=1)
    last_id = latest[0].id if latest else 0
    await client.send_message(entity, url)

    deadline = time.monotonic() + timeout_s
    clicked: set[int] = set()
    media: dict[int, Any] = {}
    last_media_at: float | None = None
    last_problem: str | None = None

    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_S)
        messages = await client.get_messages(entity, min_id=last_id, limit=40)
        incoming = [m for m in reversed(messages) if not m.out]
        for msg in incoming:
            verdict = classify_message(msg)
            if verdict == "media":
                if msg.id not in media and media_plausible(msg, expected_duration):
                    media[msg.id] = msg
                    last_media_at = time.monotonic()
            elif verdict == "buttons" and msg.id not in clicked and not media:
                pick = choose_button(msg.buttons, variant)
                clicked.add(msg.id)
                if pick:
                    log.info("relay %s: clicking button %s", username, pick)
                    try:
                        await msg.click(*pick)
                    except Exception as exc:
                        log.warning("relay %s: click failed: %s", username, exc)
            elif verdict == "junk":
                last_problem = f"junk/subscription prompt: {(msg.message or '')[:120]}"
            elif verdict == "error":
                last_problem = f"helper error: {(msg.message or '')[:120]}"
        if media and last_media_at and time.monotonic() - last_media_at >= ALBUM_QUIET_S:
            return [media[i] for i in sorted(media)]
        if last_problem and not media:
            raise RelayError(last_problem)
    if media:
        return [media[i] for i in sorted(media)]
    raise RelayError(last_problem or "timeout: no media from helper")


async def relay_fetch(
    ctx: dict[str, Any],
    key: str,
    url: str,
    platform: str,
    variant: str | None,
    channel_id: int,
    expected_duration: float | None = None,
) -> dict[str, Any]:
    settings: Settings = ctx["settings"]
    redis: Redis = ctx["redis"]
    sm: async_sessionmaker = ctx["sessionmaker"]
    client: TelegramClient = ctx["userbots"].get()

    async with sm() as session:
        helpers = await registry.pick_helpers(session, platform)
    if not helpers:
        return {"ok": False, "error": "no helper bots available"}

    last_error = "unknown"
    for helper in helpers:
        if not await _acquire(redis, helper.username, wait_s=settings.relay_timeout_s):
            last_error = f"@{helper.username} busy"
            continue
        started = time.monotonic()
        try:
            messages = await converse(
                client, helper.username, url, variant, expected_duration, settings.relay_timeout_s
            )
            total = len(messages)
            for index, msg in enumerate(messages, 1):
                await client.send_file(channel_id, msg.media, caption=key_tag(key, index, total))
                await asyncio.sleep(0.5)
            latency = int((time.monotonic() - started) * 1000)
            await redis.delete(f"xsaveasbot:relay:streak:{helper.username}")
            async with sm() as session:
                await registry.record_result(session, helper.id, ok=True, latency_ms=latency)
                await session.commit()
            log.info(
                "relay ok helper=@%s key=%s parts=%d %dms", helper.username, key, total, latency
            )
            return {"ok": True, "helper": helper.username, "parts": total}
        except FloodWaitError as exc:
            last_error = f"FloodWait {exc.seconds}s"
            log.warning("relay FloodWait %ss on @%s", exc.seconds, helper.username)
            await asyncio.sleep(min(exc.seconds, 30))
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
            log.warning("relay failed helper=@%s: %s", helper.username, last_error)
        finally:
            await _release(redis, helper.username)
        streak = int(await redis.incr(f"xsaveasbot:relay:streak:{helper.username}"))
        async with sm() as session:
            await registry.record_result(
                session, helper.id, ok=False, error=last_error, streak=streak
            )
            await session.commit()
        if streak >= registry.FAILS_BEFORE_COOLDOWN:
            await redis.delete(f"xsaveasbot:relay:streak:{helper.username}")
    return {"ok": False, "error": last_error}
