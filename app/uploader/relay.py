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
import re
import time
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker
from telethon import TelegramClient

from app.bot.media_utils import key_tag
from app.config import Settings
from app.delivery.finalize import get_meta, set_meta
from app.extractors.youtube_meta import flag_from_text
from app.relay import registry
from app.relay.parsing import (
    JOIN_MARKERS,
    back_button,
    choose_button,
    choose_language,
    classify_message,
    is_url_language_menu,
    media_plausible,
    wanted_kind,
)
from app.uploader.subscribe import auto_subscribe

log = logging.getLogger(__name__)

POLL_S = 2.0
ALBUM_QUIET_S = 5.0  # wait this long after the last media message for album siblings
STALL_S = 60.0  # give up on a helper that shows no new activity for this long


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


def _menu_key(msg: Any) -> tuple:
    return tuple((b.text or "") for row in (msg.buttons or []) for b in row)


def _new_menu(msg: Any, menus: dict[int, tuple]) -> bool:
    """True when a message we already clicked now shows a different language menu."""
    return _menu_key(msg) != menus.get(msg.id) and choose_language(msg.buttons) is not None


async def converse(
    client: TelegramClient,
    username: str,
    url: str,
    variant: str | None,
    expected_duration: float | None,
    timeout_s: float,
    wants: str = "any",
    ctx_redis: Redis | None = None,
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
    logged: set[int] = set()
    last_activity = time.monotonic()
    signature: tuple | None = None
    stall_s = STALL_S
    stale: set[int] = set()  # messages from before a subscription, ignored afterwards
    subscribed = False
    menus: dict[int, tuple] = {}
    downgraded = False
    eff_variant = variant
    redis = ctx_redis

    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_S)
        messages = await client.get_messages(entity, min_id=last_id, limit=40)
        incoming = [m for m in reversed(messages) if not m.out]
        sig = tuple((m.id, m.message or "", bool(m.media)) for m in incoming)
        if sig != signature:
            signature, last_activity = sig, time.monotonic()  # new message or edited progress
        for msg in incoming:
            if msg.id in stale:
                continue
            verdict = classify_message(msg, wants)
            if downgraded and msg.id in clicked and is_url_language_menu(msg.buttons or []):
                continue  # waiting for the helper to go back to the quality menu
            if msg.id not in logged:
                logged.add(msg.id)
                log.info(
                    "relay @%s: msg=%s verdict=%s media=%s buttons=%s text=%r",
                    username,
                    msg.id,
                    verdict,
                    type(msg.media).__name__ if msg.media else None,
                    [b.text for row in (msg.buttons or []) for b in row][:8],
                    (msg.message or "")[:80],
                )
            if verdict == "media":
                if msg.id not in media and media_plausible(msg, expected_duration):
                    media[msg.id] = msg
                    last_media_at = time.monotonic()
            elif (
                verdict == "buttons"
                and not media
                and msg.id in clicked
                and not downgraded
                and is_url_language_menu(msg.buttons or [])
            ):
                # e.g. 1080p+ opens a mini-app language picker: fall back to 720p
                downgraded, eff_variant = True, "720p"
                back = back_button(msg.buttons)
                log.info("relay @%s: %s needs a mini app; going back to 720p", username, variant)
                if back:
                    try:
                        await msg.click(*back)
                    except Exception as exc:
                        log.warning("relay %s: back click failed: %s", username, exc)
                clicked.discard(msg.id)
                menus.pop(msg.id, None)
                last_activity = time.monotonic()
            elif (
                verdict == "buttons"
                and not media
                and (msg.id not in clicked or _new_menu(msg, menus))
            ):
                if msg.id not in clicked:
                    pick = choose_button(msg.buttons, eff_variant)
                else:  # the helper edited its message into a follow-up menu (audio language)
                    pick = choose_language(msg.buttons)
                clicked.add(msg.id)
                menus[msg.id] = _menu_key(msg)
                if pick:
                    log.info(
                        "relay %s: variant=%s clicking button %s %r",
                        username,
                        variant,
                        pick,
                        msg.buttons[pick[0]][pick[1]].text,
                    )
                    try:
                        answer = await msg.click(*pick)
                    except Exception as exc:
                        log.warning("relay %s: click failed: %s", username, exc)
                    else:
                        popup = (getattr(answer, "message", None) or "").strip()
                        if popup:
                            log.info("relay @%s: button answer: %r", username, popup[:120])
                            if any(m in popup.lower() for m in JOIN_MARKERS):
                                raise RelayError(f"junk/subscription prompt: {popup[:120]}")
            elif verdict == "junk":
                if redis is not None and not subscribed and msg.buttons:
                    subscribed = True
                    if await auto_subscribe(client, redis, username, msg):
                        await asyncio.sleep(3)
                        stale |= {m.id for m in incoming}
                        last_problem, signature = None, None
                        last_activity = time.monotonic()
                        await client.send_message(entity, url)
                        break
                last_problem = f"junk/subscription prompt: {(msg.message or '')[:120]}"
            elif verdict == "error":
                last_problem = f"helper error: {(msg.message or '')[:120]}"
        if media and last_media_at and time.monotonic() - last_media_at >= ALBUM_QUIET_S:
            return [media[i] for i in sorted(media)]
        if last_problem and not media:
            raise RelayError(last_problem)
        if not media and time.monotonic() - last_activity > stall_s:
            raise RelayError("stalled: helper stopped responding")
    if media:
        return [media[i] for i in sorted(media)]
    raise RelayError(last_problem or "timeout: no media from helper")


async def _ensure_started(client: TelegramClient, redis: Redis, username: str) -> None:
    """Bots ignore users who never pressed /start: do it once per helper."""
    flag = f"xsaveasbot:relay:started:{username}"
    if await redis.get(flag):
        return
    entity = await client.get_entity(username)
    await client.send_message(entity, "/start")
    await asyncio.sleep(4)  # let the welcome message arrive before our request
    await redis.set(flag, "1")


async def _attempt(
    ctx: dict[str, Any],
    client: TelegramClient,
    helper: Any,
    url: str,
    variant: str | None,
    expected_duration: float | None,
    wants: str = "any",
) -> tuple[Any, list[Any], int]:
    """Ask one helper. Returns (helper, media messages, latency_ms) or raises."""
    settings: Settings = ctx["settings"]
    redis: Redis = ctx["redis"]
    if not await _acquire(redis, helper.username, wait_s=settings.relay_timeout_s):
        raise RelayError(f"@{helper.username} busy")
    started = time.monotonic()
    try:
        await _ensure_started(client, redis, helper.username)
        messages = await converse(
            client,
            helper.username,
            url,
            variant,
            expected_duration,
            settings.relay_timeout_s,
            wants,
            redis,
        )
        return helper, messages, int((time.monotonic() - started) * 1000)
    finally:
        await _release(redis, helper.username)


async def _record_failure(ctx: dict[str, Any], helper: Any, error: str) -> None:
    redis: Redis = ctx["redis"]
    streak = int(await redis.incr(f"xsaveasbot:relay:streak:{helper.username}"))
    async with ctx["sessionmaker"]() as session:
        await registry.record_result(session, helper.id, ok=False, error=error, streak=streak)
        await session.commit()
    if streak >= registry.FAILS_BEFORE_COOLDOWN:
        await redis.delete(f"xsaveasbot:relay:streak:{helper.username}")


async def _store_facts(redis: Redis, key: str, msg: Any) -> None:
    """Remember the real quality (video height) and audio-language flag for the caption."""
    facts: dict[str, Any] = {}
    sides = [
        min(a.w, a.h)
        for a in getattr(getattr(msg, "document", None), "attributes", None) or []
        if getattr(a, "h", None) and getattr(a, "w", None)
    ]
    if sides:
        facts["quality"] = f"{sides[0]}p"
    flag = flag_from_text(getattr(msg, "message", None))
    if flag:
        facts["flag"] = flag
    if facts:
        await set_meta(redis, key, {**await get_meta(redis, key), **facts})


async def relay_probe(
    ctx: dict[str, Any],
    username: str,
    url: str,
    variant: str | None = None,
    wants: str = "any",
) -> dict[str, Any]:
    """Admin/benchmark: ask one helper for `url`; report timing and what came back.
    Nothing is stored. `seconds` covers only the conversation (not the /start handshake)."""
    client: TelegramClient = ctx["userbots"].get()
    redis: Redis = ctx["redis"]
    started = time.monotonic()
    try:
        await _ensure_started(client, redis, username)
        started = time.monotonic()
        messages = await converse(client, username, url, variant, None, 100, wants, redis)
    except Exception as exc:
        return {
            "ok": False,
            "seconds": round(time.monotonic() - started, 1),
            "error": str(exc) or type(exc).__name__,
        }
    seconds = round(time.monotonic() - started, 1)
    first = messages[0]
    attrs = getattr(getattr(first, "document", None), "attributes", None) or []
    dims = [(a.w, a.h) for a in attrs if getattr(a, "w", None) and getattr(a, "h", None)]
    file = getattr(first, "file", None)
    return {
        "ok": True,
        "seconds": seconds,
        "media": len(messages),
        "kind": type(first.media).__name__,
        "mime": getattr(file, "mime_type", None),
        "size": getattr(file, "size", None),
        "duration": getattr(file, "duration", None),
        "dims": dims,
    }


async def send_report(ctx: dict[str, Any], username: str, text: str) -> dict[str, Any]:
    """Send a (long) text report to a user from the userbot account, in 4000-char chunks."""
    client: TelegramClient = ctx["userbots"].get()
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > 3900:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        await client.send_message(username, chunk, parse_mode=None)
        await asyncio.sleep(1)
    return {"ok": True, "messages": len(chunks)}


async def relay_fetch(
    ctx: dict[str, Any],
    key: str,
    url: str,
    platform: str,
    variant: str | None,
    channel_id: int,
    expected_duration: float | None = None,
) -> dict[str, Any]:
    """Race the best `relay_parallel` helpers; the first valid media wins, the rest are
    cancelled. If the whole batch fails, the next batch of helpers is tried."""
    settings: Settings = ctx["settings"]
    redis: Redis = ctx["redis"]
    sm: async_sessionmaker = ctx["sessionmaker"]
    client: TelegramClient = ctx["userbots"].get()

    async with sm() as session:
        helpers = await registry.pick_helpers(session, platform)
        order = await registry.get_order(session, platform, variant)
    if not helpers:
        return {"ok": False, "error": "no helper bots available"}
    if order:  # measured speed for this exact quality button, fastest first; the rest follow
        rank = {name: i for i, name in enumerate(order)}
        helpers.sort(key=lambda h: (h.username not in rank, rank.get(h.username, 0), h.priority))

    wants = wanted_kind(platform, variant)
    parallel = max(1, settings.relay_parallel)
    pending = list(helpers)
    batch_size = parallel
    if not order and variant and re.fullmatch(r"\d{3,4}p", variant):
        # an explicit quality: only some helper bots can honour it, ask them first
        quality = [h for h in helpers if h.username in settings.relay_quality_helpers]
        if quality:
            pending = quality + [h for h in helpers if h not in quality]
            batch_size = len(quality)
    last_error = "unknown"
    while pending:
        batch, pending = pending[:batch_size], pending[batch_size:]
        batch_size = parallel
        tasks = {
            asyncio.create_task(_attempt(ctx, client, h, url, variant, expected_duration, wants)): h
            for h in batch
        }
        winner: tuple[Any, list[Any], int] | None = None
        try:
            while tasks and winner is None:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    helper = tasks.pop(task)
                    try:
                        result = task.result()
                    except Exception as exc:
                        last_error = str(exc) or type(exc).__name__
                        log.warning("relay failed helper=@%s: %s", helper.username, last_error)
                        await _record_failure(ctx, helper, last_error)
                    else:
                        winner = winner or result
        finally:
            for task in tasks:
                task.cancel()  # lost the race: its lock is released in _attempt
            await asyncio.gather(*tasks, return_exceptions=True)

        if winner is None:
            continue
        helper, messages, latency = winner
        await _store_facts(redis, key, messages[0])
        try:
            total = len(messages)
            for index, msg in enumerate(messages, 1):
                await client.send_file(channel_id, msg.media, caption=key_tag(key, index, total))
                await asyncio.sleep(0.5)
        except Exception as exc:
            last_error = f"copy failed: {exc}"
            log.warning("relay copy failed helper=@%s: %s", helper.username, exc)
            await _record_failure(ctx, helper, last_error)
            continue
        await redis.delete(f"xsaveasbot:relay:streak:{helper.username}")
        async with sm() as session:
            await registry.record_result(session, helper.id, ok=True, latency_ms=latency)
            await session.commit()
        log.info("relay ok helper=@%s key=%s parts=%d %dms", helper.username, key, total, latency)
        return {"ok": True, "helper": helper.username, "parts": total}
    return {"ok": False, "error": last_error}
