"""Self-download vs helper-bot race, decided per quality button.

The first RACE_SAMPLES requests of each quality run both paths at once and the first to
deliver wins; after that the faster path (more wins, faster on average on a tie) is used
for that quality alone. Qualities a helper cannot honour (1080p and up) never race."""

from __future__ import annotations

from redis.asyncio import Redis

RACE_SAMPLES = 10
RACE_VARIANTS = ("360p", "480p", "720p", "1080p", "mp3")


def _k(variant: str) -> str:
    return f"xsaveasbot:race:youtube:{variant}"


async def stats(redis: Redis, variant: str) -> dict[str, float]:
    raw = await redis.hgetall(_k(variant))
    out = {"self": 0.0, "relay": 0.0, "self_s": 0.0, "relay_s": 0.0}
    for field, value in raw.items():
        name = field.decode() if isinstance(field, bytes) else field
        out[name] = float(value)
    return out


async def route(redis: Redis, variant: str | None) -> str:
    """'race' while sampling, then 'self' or 'relay'; 'self' for qualities that cannot race."""
    if variant not in RACE_VARIANTS:
        return "self"
    s = await stats(redis, variant)
    if s["self"] + s["relay"] < RACE_SAMPLES:
        return "race"
    if s["self"] != s["relay"]:
        return "self" if s["self"] > s["relay"] else "relay"
    avg_self = s["self_s"] / s["self"] if s["self"] else float("inf")
    avg_relay = s["relay_s"] / s["relay"] if s["relay"] else float("inf")
    return "relay" if avg_relay < avg_self else "self"


async def record(redis: Redis, variant: str, winner: str, seconds: float) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hincrbyfloat(_k(variant), winner, 1)
        pipe.hincrbyfloat(_k(variant), f"{winner}_s", seconds)
        await pipe.execute()


async def reset(redis: Redis, variant: str | None = None) -> None:
    for v in [variant] if variant else RACE_VARIANTS:
        await redis.delete(_k(v))
