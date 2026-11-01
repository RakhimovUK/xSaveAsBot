"""Collect storage-channel parts, write the cache and deliver to everyone waiting.

Used by the bot (channel_post of userbot / relay uploads) and by the worker (url-send,
where the Bot API response already carries the file_id).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.sender import Sender
from app.config import Settings
from app.delivery import cache
from app.delivery.cache import StoredPart
from app.delivery.captions import build_caption
from app.delivery.pending import PendingDelivery, pop_waiters
from app.delivery.send import deliver_parts

log = logging.getLogger(__name__)

TTL_S = 3600


def _k(prefix: str, key: str) -> str:
    return f"xsaveasbot:{prefix}:{key}"


async def set_meta(redis: Redis, key: str, meta: dict) -> None:
    await redis.set(_k("meta", key), json.dumps(meta), ex=TTL_S)


async def get_meta(redis: Redis, key: str) -> dict:
    raw = await redis.get(_k("meta", key))
    return json.loads(raw) if raw else {}


async def mark_done(redis: Redis, key: str) -> None:
    await redis.set(_k("done", key), "1", ex=120)


async def is_done(redis: Redis, key: str) -> bool:
    return bool(await redis.exists(_k("done", key)))


async def clear_done(redis: Redis, key: str) -> None:
    await redis.delete(_k("done", key))


async def put_part(
    redis: Redis, key: str, index: int, total: int, part: StoredPart
) -> list[StoredPart] | None:
    """Store one storage post. Returns all parts (ordered) once the last one arrived,
    exactly once per key, otherwise None."""
    hkey = _k("parts", key)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(hkey, str(index), json.dumps(asdict(part)))
        pipe.expire(hkey, TTL_S)
        pipe.hlen(hkey)
        *_, count = await pipe.execute()
    if int(count) < total:
        return None
    if not await redis.set(_k("final", key), "1", nx=True, ex=600):
        return None
    raw = await redis.hgetall(hkey)
    await redis.delete(hkey)
    ordered = sorted(raw.items(), key=lambda kv: int(kv[0]))
    return [StoredPart(**json.loads(v)) for _, v in ordered]


async def deliver_waiter(
    sender: Sender, waiter: PendingDelivery, parts: list[StoredPart], caption: str | None
) -> None:
    try:
        await deliver_parts(sender, waiter.target, parts, caption)
    except Exception:
        log.exception("delivery failed target=%s", waiter.target)
    await sender.delete(waiter.target.chat_id, waiter.status_message_id)


async def finalize(
    *,
    redis: Redis,
    session: AsyncSession,
    sender: Sender,
    settings: Settings,
    bot_username: str | None,
    key: str,
    parts: list[StoredPart],
) -> None:
    meta = await get_meta(redis, key)
    caption = build_caption(
        meta.get("caption") or meta.get("title"), meta.get("source_url"), bot_username
    )
    platform = meta.get("platform") or key.split(":", 1)[0]
    await cache.save_entry(session, key, platform, parts, caption)
    await session.commit()
    waiters = await pop_waiters(redis, key)
    log.info("finalize key=%s parts=%d waiters=%d", key, len(parts), len(waiters))
    for waiter in waiters:
        await deliver_waiter(sender, waiter, parts, caption)
    await mark_done(redis, key)
    await redis.delete(_k("final", key))
