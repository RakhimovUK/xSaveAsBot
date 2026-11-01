"""Daily egress budget (bytes we upload from our own server) and url-send success rates."""

from __future__ import annotations

from datetime import UTC, datetime

from redis.asyncio import Redis

from app.config import Settings

GB = 1024**3


def _day_key() -> str:
    return f"xsaveasbot:egress:{datetime.now(UTC):%Y%m%d}"


async def used_bytes(redis: Redis) -> int:
    return int(await redis.get(_day_key()) or 0)


async def add_bytes(redis: Redis, amount: int) -> None:
    key = _day_key()
    await redis.incrby(key, amount)
    await redis.expire(key, 3 * 24 * 3600)


async def over_budget(redis: Redis, settings: Settings, need: int = 0) -> bool:
    return await used_bytes(redis) + need > settings.egress_daily_budget_gb * GB


# --- url-send success tracking: auto-disable a platform whose CDN blocks Telegram ---

MIN_ATTEMPTS = 10
MAX_FAIL_RATE = 0.7


def _url_key(platform: str, outcome: str) -> str:
    return f"xsaveasbot:urlsend:{platform}:{outcome}"


async def record_url_send(redis: Redis, platform: str, ok: bool) -> None:
    key = _url_key(platform, "ok" if ok else "fail")
    await redis.incr(key)
    await redis.expire(key, 7 * 24 * 3600)


async def url_send_allowed(redis: Redis, platform: str) -> bool:
    ok = int(await redis.get(_url_key(platform, "ok")) or 0)
    fail = int(await redis.get(_url_key(platform, "fail")) or 0)
    total = ok + fail
    return total < MIN_ATTEMPTS or fail / total <= MAX_FAIL_RATE


async def url_send_stats(redis: Redis, platform: str) -> tuple[int, int]:
    ok = int(await redis.get(_url_key(platform, "ok")) or 0)
    fail = int(await redis.get(_url_key(platform, "fail")) or 0)
    return ok, fail
