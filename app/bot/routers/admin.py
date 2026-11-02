"""Admin commands (admin IDs from env). Admin-only text is English by design."""

from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message
from arq import ArqRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.sender import Sender
from app.bot.targets import target_for_message
from app.config import Settings
from app.db.models import Download, Group, MediaCache, User
from app.delivery import race
from app.delivery.egress import GB, url_send_stats, used_bytes
from app.extractors.url_utils import ALL_PLATFORMS
from app.queue import UPLOADER_QUEUE, WORKER_QUEUE
from app.relay import registry

router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return settings.is_admin(message.from_user.id if message.from_user else None)


router.message.filter(IsAdmin())

HELPERS_USAGE = (
    "Usage:\n"
    "/helper_add @username [platforms|all] [priority]\n"
    "/helper_remove @username\n"
    "/helper_on @username · /helper_off @username\n"
    "/helpers"
)


async def _reply(message: Message, sender: Sender, group: Group | None, text: str) -> None:
    await sender.text(target_for_message(message, group), text)


@router.message(Command("helpers"))
async def cmd_helpers(
    message: Message, sender: Sender, session: AsyncSession, db_group: Group | None
) -> None:
    helpers = await registry.list_helpers(session)
    if not helpers:
        await _reply(message, sender, db_group, "No helper bots yet.\n\n" + HELPERS_USAGE)
        return
    now = datetime.now(UTC)
    lines = ["<b>Helper bots</b>"]
    for h in helpers:
        cooldown = registry._aware(h.cooldown_until)
        state = "off" if not h.enabled else "cooldown" if cooldown and cooldown > now else "on"
        lines.append(
            f"@{html.escape(h.username)} [{state}] prio={h.priority} "
            f"platforms={html.escape(h.platforms)}\n"
            f"  ok={h.success} fail={h.fail} avg={h.avg_latency_ms / 1000:.1f}s"
            + (f"\n  last error: {html.escape(h.last_error)}" if h.last_error else "")
        )
    await _reply(message, sender, db_group, "\n".join(lines))


@router.message(Command("helper_add"))
async def cmd_helper_add(
    message: Message,
    command: CommandObject,
    sender: Sender,
    session: AsyncSession,
    db_group: Group | None,
) -> None:
    args = (command.args or "").split()
    if not args:
        await _reply(message, sender, db_group, HELPERS_USAGE)
        return
    platforms = args[1] if len(args) > 1 else "all"
    unknown = [p for p in platforms.lower().split(",") if p != "all" and p not in ALL_PLATFORMS]
    if unknown:
        await _reply(
            message, sender, db_group, f"Unknown platform(s): {html.escape(','.join(unknown))}"
        )
        return
    priority = int(args[2]) if len(args) > 2 and args[2].isdigit() else 100
    helper = await registry.add_helper(session, args[0], platforms, priority)
    await _reply(
        message,
        sender,
        db_group,
        f"✅ @{html.escape(helper.username)} saved (platforms={html.escape(helper.platforms)}, "
        f"priority={helper.priority})",
    )


@router.message(Command("helper_remove", "helper_on", "helper_off"))
async def cmd_helper_toggle(
    message: Message,
    command: CommandObject,
    sender: Sender,
    session: AsyncSession,
    db_group: Group | None,
) -> None:
    username = (command.args or "").strip()
    if not username:
        await _reply(message, sender, db_group, HELPERS_USAGE)
        return
    if command.command == "helper_remove":
        done = await registry.remove_helper(session, username)
    else:
        done = await registry.set_enabled(session, username, command.command == "helper_on")
    await _reply(message, sender, db_group, "✅ done" if done else "❌ no such helper")


@router.message(Command("race"))
async def cmd_race(
    message: Message, command: CommandObject, sender: Sender, arq: ArqRedis, db_group: Group | None
) -> None:
    """YouTube self-vs-relay race table; `/race reset [quality]` starts sampling over."""
    args = (command.args or "").split()
    if args and args[0] == "reset":
        await race.reset(arq, args[1] if len(args) > 1 else None)
        await _reply(message, sender, db_group, "✅ race statistics reset")
        return
    lines = [f"<b>Race</b> (first {race.RACE_SAMPLES} per quality, then the faster path)"]
    for variant in race.RACE_VARIANTS:
        s = await race.stats(arq, variant)
        lane = await race.route(arq, variant)
        lines.append(
            f"{variant}: server {int(s['self'])} wins"
            + (f" (avg {s['self_s'] / s['self']:.0f}s)" if s["self"] else "")
            + f" · helper {int(s['relay'])} wins"
            + (f" (avg {s['relay_s'] / s['relay']:.0f}s)" if s["relay"] else "")
            + f" → {lane}"
        )
    lines.append("1080p and up: server only")
    await _reply(message, sender, db_group, "\n".join(lines))


@router.message(Command("ban", "unban"))
async def cmd_ban(
    message: Message,
    command: CommandObject,
    sender: Sender,
    session: AsyncSession,
    db_group: Group | None,
) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await _reply(message, sender, db_group, "Usage: /ban <user_id> · /unban <user_id>")
        return
    user = await session.get(User, int(arg))
    if user is None:
        await _reply(message, sender, db_group, "❌ unknown user (they must have used the bot)")
        return
    user.is_banned = command.command == "ban"
    await _reply(
        message, sender, db_group, f"✅ {arg} {'banned' if user.is_banned else 'unbanned'}"
    )


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    sender: Sender,
    session: AsyncSession,
    settings: Settings,
    arq: ArqRedis,
    db_group: Group | None,
) -> None:
    since = datetime.now(UTC) - timedelta(hours=24)
    users = await session.scalar(select(func.count()).select_from(User))
    dau = await session.scalar(select(func.count()).where(User.last_seen_at >= since))
    rows = (
        await session.execute(
            select(Download.platform, Download.method, Download.status, func.count())
            .where(Download.created_at >= since)
            .group_by(Download.platform, Download.method, Download.status)
        )
    ).all()
    by_platform: dict[str, list[int]] = {}
    by_method: dict[str, int] = {}
    ok_total = fail_total = 0
    for platform, method, status, count in rows:
        slot = by_platform.setdefault(platform or "?", [0, 0])
        if status == "ok":
            slot[0] += count
            ok_total += count
            by_method[method or "?"] = by_method.get(method or "?", 0) + count
        else:
            slot[1] += count
            fail_total += count
    cached = await session.scalar(select(func.count()).select_from(MediaCache))
    hits = await session.scalar(select(func.coalesce(func.sum(MediaCache.hits), 0)))
    egress = await used_bytes(arq)

    lines = [
        "<b>Stats</b>",
        f"Users: {users} · active 24h: {dau}",
        f"Requests 24h: ok={ok_total} fail={fail_total}",
        "Methods: " + (", ".join(f"{m}={c}" for m, c in sorted(by_method.items())) or "—"),
        "Platforms (ok/fail): "
        + (", ".join(f"{p}={v[0]}/{v[1]}" for p, v in sorted(by_platform.items())) or "—"),
        f"Cache: {cached} items, {hits} hits",
        f"Egress today: {egress / GB:.2f} / {settings.egress_daily_budget_gb} GB",
    ]
    url_lines = []
    for platform in ALL_PLATFORMS:
        ok, fail = await url_send_stats(arq, platform)
        if ok or fail:
            url_lines.append(f"{platform}={ok}/{fail}")
    if url_lines:
        lines.append("URL-send (ok/fail): " + ", ".join(url_lines))
    await _reply(message, sender, db_group, "\n".join(lines))


@router.message(Command("health"))
async def cmd_health(
    message: Message,
    sender: Sender,
    session: AsyncSession,
    settings: Settings,
    arq: ArqRedis,
    db_group: Group | None,
) -> None:
    async def probe(name: str, queue: str, *args: str) -> str:
        try:
            job = await arq.enqueue_job(name, *args, _queue_name=queue)
            return html.escape(str(await job.result(timeout=15)))
        except Exception as exc:
            return f"❌ {html.escape(repr(exc))}"

    worker = await probe("ping", WORKER_QUEUE, "health")
    userbot = await probe("userbot_status", UPLOADER_QUEUE)
    helpers = await registry.list_helpers(session)
    active = [h for h in helpers if h.enabled]
    lines = [
        "<b>Health</b>",
        f"Worker: {worker}",
        f"Userbot: {userbot}",
        f"Helper bots: {len(active)} enabled / {len(helpers)} total",
        f"Platforms: {', '.join(settings.platforms_enabled)}",
        f"Flags: relay={settings.feature_relay} url_send={settings.feature_url_send} "
        f"relay_tier2={settings.relay_tier2}",
    ]
    await _reply(message, sender, db_group, "\n".join(lines))
