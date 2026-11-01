"""Pending deliveries: cache key -> everyone waiting for it (brief section 5).

When the storage-channel post for a key arrives, the bot pops all waiters and
delivers to each one in its own chat and topic. A non-empty list also means the key
is already in flight (dedup).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from redis.asyncio import Redis

from app.bot.reply_target import ReplyTarget

PENDING_TTL_S = 3600


def _redis_key(key: str) -> str:
    return f"xsaveasbot:pending:{key}"


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    target: ReplyTarget
    lang: str
    user_id: int | None = None
    status_message_id: int | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "target": json.loads(self.target.to_json()),
                "lang": self.lang,
                "user_id": self.user_id,
                "status_message_id": self.status_message_id,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> PendingDelivery:
        data = json.loads(raw)
        return cls(
            target=ReplyTarget(**data["target"]),
            lang=data["lang"],
            user_id=data.get("user_id"),
            status_message_id=data.get("status_message_id"),
        )


async def add_waiter(redis: Redis, key: str, waiter: PendingDelivery) -> bool:
    """Register a waiter. Returns True if this is the first one (caller should start the job)."""
    rkey = _redis_key(key)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.rpush(rkey, waiter.to_json())
        pipe.expire(rkey, PENDING_TTL_S)
        length, _ = await pipe.execute()
    return int(length) == 1


async def pop_waiters(redis: Redis, key: str) -> list[PendingDelivery]:
    rkey = _redis_key(key)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lrange(rkey, 0, -1)
        pipe.delete(rkey)
        raw, _ = await pipe.execute()
    return [PendingDelivery.from_json(item) for item in raw]
