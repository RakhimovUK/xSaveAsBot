"""Helper-bot registry (DB) used by the uploader relay and the admin commands."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HelperBot, Setting

FAILS_BEFORE_COOLDOWN = 3
COOLDOWN = timedelta(minutes=10)


def normalize_username(raw: str) -> str:
    return raw.strip().lstrip("@").lower()


def supports(helper: HelperBot, platform: str) -> bool:
    wanted = {p.strip().lower() for p in helper.platforms.split(",") if p.strip()}
    return "all" in wanted or platform in wanted


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def list_helpers(session: AsyncSession) -> list[HelperBot]:
    rows = await session.scalars(select(HelperBot).order_by(HelperBot.priority, HelperBot.id))
    return list(rows)


async def pick_helpers(session: AsyncSession, platform: str) -> list[HelperBot]:
    """Enabled helpers for a platform, not cooling down, best first."""
    now = datetime.now(UTC)
    result = []
    for helper in await list_helpers(session):
        cooldown = _aware(helper.cooldown_until)
        if helper.enabled and supports(helper, platform) and (cooldown is None or cooldown <= now):
            result.append(helper)
    return result


def _order_key(platform: str, variant: str | None) -> str:
    return f"relay_order:{platform}:{variant or 'best'}"


async def get_order(session: AsyncSession, platform: str, variant: str | None) -> list[str]:
    """Usernames in the order measured by the benchmark for one platform + quality button."""
    row = await session.get(Setting, _order_key(platform, variant))
    if row is None:
        return []
    try:
        return [str(u) for u in json.loads(row.value)]
    except ValueError:
        return []


async def set_order(
    session: AsyncSession, platform: str, variant: str | None, usernames: list[str]
) -> None:
    key = _order_key(platform, variant)
    value = json.dumps([normalize_username(u) for u in usernames])
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


async def get_helper(session: AsyncSession, username: str) -> HelperBot | None:
    return await session.scalar(
        select(HelperBot).where(HelperBot.username == normalize_username(username))
    )


async def add_helper(
    session: AsyncSession, username: str, platforms: str = "all", priority: int = 100
) -> HelperBot:
    helper = await get_helper(session, username)
    if helper is None:
        helper = HelperBot(username=normalize_username(username))
        session.add(helper)
    helper.platforms = platforms.lower()
    helper.priority = priority
    helper.enabled = True
    helper.cooldown_until = None
    await session.flush()
    return helper


async def remove_helper(session: AsyncSession, username: str) -> bool:
    helper = await get_helper(session, username)
    if helper is None:
        return False
    await session.delete(helper)
    return True


async def set_enabled(session: AsyncSession, username: str, enabled: bool) -> bool:
    helper = await get_helper(session, username)
    if helper is None:
        return False
    helper.enabled = enabled
    if enabled:
        helper.cooldown_until = None
    return True


async def record_result(
    session: AsyncSession,
    helper_id: int,
    *,
    ok: bool,
    latency_ms: int = 0,
    error: str | None = None,
    streak: int = 0,
) -> None:
    """Update counters. `streak` = consecutive failures including this one."""
    helper = await session.get(HelperBot, helper_id)
    if helper is None:
        return
    if ok:
        helper.success += 1
        helper.avg_latency_ms = (
            latency_ms
            if helper.success == 1
            else int(helper.avg_latency_ms * 0.8 + latency_ms * 0.2)
        )
        helper.cooldown_until = None
    else:
        helper.fail += 1
        helper.last_error = (error or "")[:500]
        if streak >= FAILS_BEFORE_COOLDOWN:
            helper.cooldown_until = datetime.now(UTC) + COOLDOWN
