"""The delivery ladder (brief section 2): cache -> url-send -> relay -> self download.

Runs inside the worker. It never moves media bytes to the user itself: results land in a
storage channel, get a bot file_id, and are delivered by `finalize` to every waiting
ReplyTarget (own chat and forum topic).
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.media_utils import extract_file, key_tag
from app.bot.sender import Sender
from app.config import Settings
from app.db.models import Download
from app.delivery import cache, race
from app.delivery.cache import StoredPart
from app.delivery.egress import (
    GB,
    add_bytes,
    over_budget,
    record_url_send,
    url_send_allowed,
)
from app.delivery.finalize import deliver_waiter, finalize, is_done, set_meta
from app.delivery.jobs import LinkJob
from app.delivery.pending import PendingDelivery, add_waiter, pop_waiters
from app.extractors import service
from app.extractors.base import MediaInfo
from app.extractors.errors import (
    ExtractError,
    TemporaryError,
    TooLargeError,
    TooLongError,
    UnsupportedError,
    is_relayable,
)
from app.extractors.url_utils import CORE_PLATFORMS, Detected, detect_resolved
from app.extractors.youtube_meta import caption_html, fetch_oembed, flag_from_lang
from app.i18n import gettext
from app.queue import UPLOADER_QUEUE

log = logging.getLogger(__name__)

YT_BLOCKED_FLAG = "xsaveasbot:yt:probe_blocked"
QUALITY_LABELS = {"1440p": "2K (1440p)", "2160p": "4K (2160p)"}

MB = 1024 * 1024
KNOWN_ERRORS = {
    "unsupported",
    "disabled",
    "private",
    "notfound",
    "age",
    "toolarge",
    "toolong",
    "unavailable",
    "budget",
    "ratelimit",
    "nostorage",
    "generic",
}


def fmt_size(size: int | None) -> str:
    if not size:
        return ""
    return f"{size / GB:.1f} GB" if size >= GB else f"{max(1, round(size / MB))} MB"


class Processor:
    def __init__(
        self,
        *,
        settings: Settings,
        redis: ArqRedis,
        sessionmaker: async_sessionmaker[AsyncSession],
        sender: Sender,
        bot_username: str | None,
    ) -> None:
        self.s = settings
        self.redis = redis
        self.sm = sessionmaker
        self.sender = sender
        self.bot_username = bot_username

    # --- entrypoint ----------------------------------------------------------

    async def run(self, job: LinkJob) -> None:
        started = time.monotonic()
        waiter = PendingDelivery(
            target=job.reply_target,
            lang=job.lang,
            user_id=job.user_id,
            status_message_id=job.status_message_id,
        )
        key: str | None = None
        platform: str | None = None
        method: str | None = None
        egress = 0
        error_code: str | None = None
        try:
            det = await detect_resolved(job.url)
            if det is None:
                raise UnsupportedError("unsupported link", code="unsupported")
            platform = det.platform
            if platform not in self.s.platforms_enabled:
                raise UnsupportedError("platform disabled", code="disabled")

            variant = job.variant
            info: MediaInfo | None = None
            force_relay = False
            if platform == "youtube" and variant is not None:
                # the picker was shown because the direct probe is blocked: don't probe again
                force_relay = bool(await self.redis.get(YT_BLOCKED_FLAG))
            if platform == "youtube" and variant is None:
                try:
                    info = await service.probe(det.url, det.key or "", platform, self.s)
                except ExtractError as exc:
                    if not (self._relay_enabled(platform) and is_relayable(exc)):
                        raise
                    log.info(
                        "youtube probe blocked (%s); offering relay picker", type(exc).__name__
                    )
                    await self.redis.set(YT_BLOCKED_FLAG, "1", ex=900)
                    await self._send_relay_picker(job, det)
                    return
                else:
                    self._check_duration(info)
                    if info.formats:
                        await self._send_picker(job, det, info)
                        return
                    variant = "best"

            key = (det.key or "") + (f":{variant}" if variant else "")

            async with self.sm() as session:
                cached = await cache.get_entry(session, key)
                await session.commit()
            if cached is not None:
                await deliver_waiter(self.sender, waiter, cached.parts, cached.caption)
                method = "cache"
                return

            if not await add_waiter(self.redis, key, waiter):
                await self._status(job, "status-queued-shared")
                method = "shared"
                return

            method, egress = await self._ladder(job, det, variant, key, info, force_relay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_code = exc.code if isinstance(exc, ExtractError) else "generic"
            if isinstance(exc, ExtractError):
                log.warning("job failed key=%s code=%s: %s", key, error_code, str(exc)[:300])
            else:
                log.exception("job crashed key=%s", key)
            await self._fail(waiter, key, error_code)
        finally:
            await self._record(
                job.user_id,
                platform,
                key,
                method,
                error_code,
                egress,
                int((time.monotonic() - started) * 1000),
            )

    # --- ladder --------------------------------------------------------------

    async def _ladder(
        self,
        job: LinkJob,
        det: Detected,
        variant: str | None,
        key: str,
        info: MediaInfo | None,
        force_relay: bool,
    ) -> tuple[str, int]:
        s = self.s
        platform = det.platform
        channel = s.storage_channel_for(platform)
        extra: dict[str, Any] = {}
        if platform == "youtube":
            yt = await fetch_oembed(det.url)
            if yt:
                extra["caption_html"] = caption_html(det.url, yt)
            if variant and re.fullmatch(r"\d{3,4}p", variant):
                extra["quality"] = variant
            lang = ((info.raw or {}).get("language") if info else None) or None
            if flag := flag_from_lang(lang):
                extra["flag"] = flag
        await set_meta(self.redis, key, {"platform": platform, "source_url": det.url, **extra})
        relay_tried = False
        last_error: Exception | None = None

        if info is None and not force_relay:
            await self._status(job, "status-analyzing")
            try:
                info = await service.probe(det.url, det.key or "", platform, s)
            except ExtractError as exc:
                if not (self._relay_enabled(platform) and is_relayable(exc)):
                    raise
                last_error = exc

        if info is not None:
            self._check_duration(info)
            await set_meta(
                self.redis,
                key,
                {
                    "platform": platform,
                    "source_url": det.url,
                    "caption": info.caption,
                    "title": info.title,
                    "performer": info.uploader,
                    "duration": info.duration,
                    **extra,
                },
            )
            if await self._can_url_send(platform, info, variant):
                try:
                    await self._url_send(info, key, channel, platform)
                    return "url", 0
                except Exception as exc:
                    log.warning("url-send failed key=%s: %s", key, exc)
                    last_error = exc

            size = info.total_size
            if platform == "youtube" and self._relay_enabled(platform):
                lane = await race.route(self.redis, variant)
                if lane == "race":
                    return await self._race(job, det, variant, key, channel, info)
                if lane == "relay":
                    try:
                        await self._relay(job, det, variant, key, channel, info)
                        return "relay", 0
                    except Exception as exc:
                        log.warning("relay lane failed key=%s: %s", key, exc)
                        last_error = exc
            explicit_hd = platform == "youtube" and variant not in (None, "best")
            # helpers cannot honour an explicit YouTube quality, so never trade it for size
            if (
                size
                and size > s.relay_threshold_mb * MB
                and not explicit_hd
                and self._relay_enabled(platform)
            ):
                relay_tried = True
                try:
                    await self._relay(job, det, variant, key, channel, info)
                    return "relay", 0
                except Exception as exc:
                    log.warning("relay failed key=%s: %s", key, exc)
                    last_error = exc

            try:
                return "self", await self._self(job, info, det, variant, key, channel)
            except ExtractError as exc:
                last_error = exc
                if relay_tried or not (self._relay_enabled(platform) and is_relayable(exc)):
                    raise

        # probe failed with a relayable error, forced relay, or self download failed
        if not self._relay_enabled(platform):
            raise last_error or TemporaryError("nothing worked")
        await self._relay(job, det, variant, key, channel, info)
        return "relay", 0

    def _relay_enabled(self, platform: str) -> bool:
        return self.s.feature_relay and (platform in CORE_PLATFORMS or self.s.relay_tier2)

    def _check_duration(self, info: MediaInfo) -> None:
        limit = self.s.max_duration_min * 60
        if info.duration and info.duration > limit:
            raise TooLongError(f"duration {info.duration}s > {limit}s")

    async def _can_url_send(self, platform: str, info: MediaInfo, variant: str | None) -> bool:
        s = self.s
        if not s.feature_url_send or platform == "youtube" or variant == "mp3":
            return False
        if not info.all_direct or not await url_send_allowed(self.redis, platform):
            return False
        for item in info.items:
            limit = s.url_send_photo_max_mb if item.kind == "photo" else s.url_send_max_mb
            if item.size and item.size > limit * MB:
                return False
        return True

    async def _url_send(self, info: MediaInfo, key: str, channel: int, platform: str) -> None:
        """Telegram fetches the CDN URL itself: zero bytes through our server."""
        parts: list[StoredPart] = []
        total = len(info.items)
        try:
            for index, item in enumerate(info.items, 1):
                extra: dict[str, Any] = {}
                if item.kind == "video":
                    extra = {"supports_streaming": True}
                    for name in ("width", "height"):
                        if getattr(item, name):
                            extra[name] = getattr(item, name)
                    if item.duration:
                        extra["duration"] = int(item.duration)
                msg = await self.sender.to_channel(
                    item.kind, channel, item.url, key_tag(key, index, total), **extra
                )
                stored = extract_file(msg)
                if stored is None:
                    raise TemporaryError("url-send response had no file")
                parts.append(
                    StoredPart(
                        stored.kind,
                        stored.file_id,
                        stored.file_unique_id,
                        stored.size,
                        msg.chat.id,
                        msg.message_id,
                    )
                )
        except Exception:
            await record_url_send(self.redis, platform, False)
            raise
        await record_url_send(self.redis, platform, True)
        await self._finalize(key, parts)

    async def _finalize(self, key: str, parts: list[StoredPart]) -> None:
        async with self.sm() as session:
            await finalize(
                redis=self.redis,
                session=session,
                sender=self.sender,
                settings=self.s,
                bot_username=self.bot_username,
                key=key,
                parts=parts,
            )

    async def _enqueue_wait(self, name: str, *args: Any, timeout: float) -> dict[str, Any]:
        queued = await self.redis.enqueue_job(name, *args, _queue_name=UPLOADER_QUEUE)
        if queued is None:
            raise TemporaryError("could not enqueue uploader job")
        result = await queued.result(timeout=timeout)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    async def _relay(
        self,
        job: LinkJob,
        det: Detected,
        variant: str | None,
        key: str,
        channel: int,
        info: MediaInfo | None,
    ) -> None:
        quality = "MP3" if variant == "mp3" else variant if variant and variant != "best" else None
        if quality:
            await self._status(job, "status-relay-quality", quality=quality)
        else:
            await self._status(job, "status-relay")
        result = await self._enqueue_wait(
            "relay_fetch",
            key,
            det.url,
            det.platform,
            variant,
            channel,
            info.duration if info else None,
            timeout=self.s.relay_timeout_s * 3 + 60,
        )
        if not result.get("ok"):
            raise TemporaryError(str(result.get("error") or "relay failed"))
        await self._wait_done(key)

    async def _self(
        self,
        job: LinkJob,
        info: MediaInfo,
        det: Detected,
        variant: str | None,
        key: str,
        channel: int,
    ) -> int:
        s = self.s
        limit = s.max_self_upload_mb * MB
        hint = info.total_size or 0
        if hint > limit:
            raise TooLargeError(f"{hint} bytes > {limit}")
        if await over_budget(self.redis, s, hint):
            raise ExtractError("egress budget reached", code="budget")
        workdir = Path(s.jobs_dir) / uuid.uuid4().hex
        try:
            await self._status(job, "status-downloading")
            files = await service.fetch_files(info, det.url, det.platform, variant, workdir, s)
            total = sum(f.size for f in files)
            if total > limit:
                raise TooLargeError(f"{total} bytes > {limit}")
            if await over_budget(self.redis, s, total):
                raise ExtractError("egress budget reached", code="budget")
            await self._status(job, "status-uploading")
            result = await self._enqueue_wait(
                "upload_files", key, channel, [asdict(f) for f in files], timeout=3600
            )
            if not result.get("ok"):
                raise TemporaryError(str(result.get("error") or "upload failed"))
            await add_bytes(self.redis, total)
            await self._wait_done(key)
            return total
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _race(
        self,
        job: LinkJob,
        det: Detected,
        variant: str | None,
        key: str,
        channel: int,
        info: MediaInfo,
    ) -> tuple[str, int]:
        """Run the server download and the helper relay together; the first to deliver wins."""
        started = time.monotonic()
        tasks: dict[asyncio.Task, str] = {
            asyncio.create_task(self._self(job, info, det, variant, key, channel)): "self",
            asyncio.create_task(self._relay(job, det, variant, key, channel, info)): "relay",
        }
        winner: tuple[str, int] | None = None
        last_error: Exception | None = None
        try:
            while tasks and winner is None:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    name = tasks.pop(task)
                    try:
                        result = task.result()
                    except Exception as exc:
                        last_error = exc
                        log.warning("race: %s path failed key=%s: %s", name, key, exc)
                        continue
                    winner = (name, result if isinstance(result, int) else 0)
                    break
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if winner is None:
            raise last_error or TemporaryError("both race paths failed")
        seconds = time.monotonic() - started
        await race.record(self.redis, variant or "", winner[0], seconds)
        log.info("race key=%s winner=%s %.1fs", key, winner[0], seconds)
        return ("self" if winner[0] == "self" else "relay"), winner[1]

    async def _wait_done(self, key: str, seconds: float = 30) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if await is_done(self.redis, key):
                return
            await asyncio.sleep(0.5)
        raise ExtractError("storage post never reached the bot", code="nostorage")

    # --- YouTube picker --------------------------------------------------------

    async def _send_picker(self, job: LinkJob, det: Detected, info: MediaInfo) -> None:
        vid = (det.key or "").split(":", 1)[1]
        async with self.sm() as session:
            ready = await cache.cached_keys(
                session, [f"yt:{vid}:{o.variant}" for o in info.formats]
            )
        buttons = [
            InlineKeyboardButton(
                text=f"{'🚀' if f'yt:{vid}:{o.variant}' in ready else '⚡'} "
                f"{QUALITY_LABELS.get(o.variant, o.variant)}"
                + (f" · {fmt_size(o.size)}" if o.size else ""),
                callback_data=f"yv:{vid}:{o.variant}",
            )
            for o in info.formats
        ]
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        mp3_mark = "🚀" if f"yt:{vid}:mp3" in await self._cached(vid, ["mp3"]) else "⚡"
        rows.append([InlineKeyboardButton(text=f"{mp3_mark} MP3", callback_data=f"yv:{vid}:mp3")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        title = html.escape((info.title or "YouTube")[:200])
        text = gettext(job.lang, "picker-title", title=title)
        target = job.reply_target
        if not await self.sender.edit_status(
            text,
            chat_id=target.chat_id,
            message_id=job.status_message_id,
            reply_markup=markup,
        ):
            await self.sender.text(target, text, reply_markup=markup)

    async def _cached(self, vid: str, variants: list[str]) -> set[str]:
        async with self.sm() as session:
            return await cache.cached_keys(session, [f"yt:{vid}:{v}" for v in variants])

    async def _send_relay_picker(self, job: LinkJob, det: Detected) -> None:
        """Direct probe is blocked: fixed quality choices, honoured by helpers that can."""
        vid = (det.key or "").split(":", 1)[1]
        meta = await fetch_oembed(det.url)
        rows = [
            [InlineKeyboardButton(text=f"🎬 {q}", callback_data=f"yv:{vid}:{q}") for q in pair]
            for pair in (("360p", "480p"), ("720p", "1080p"))
        ]
        rows.append([InlineKeyboardButton(text="🎧 MP3", callback_data=f"yv:{vid}:mp3")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        title = html.escape((meta["title"] if meta else "YouTube")[:200])
        text = gettext(job.lang, "picker-title", title=title)
        target = job.reply_target
        if not await self.sender.edit_status(
            text,
            chat_id=target.chat_id,
            message_id=job.status_message_id,
            reply_markup=markup,
        ):
            await self.sender.text(target, text, reply_markup=markup)

    # --- helpers ---------------------------------------------------------------

    async def _status(self, job: LinkJob, key: str, **args: str) -> None:
        await self.sender.edit_status(
            gettext(job.lang, key, **args),
            chat_id=job.reply_target.chat_id,
            message_id=job.status_message_id,
        )

    async def _fail(self, waiter: PendingDelivery, key: str | None, code: str) -> None:
        waiters = await pop_waiters(self.redis, key) if key else []
        if waiter not in waiters:
            waiters.append(waiter)
        code = code if code in KNOWN_ERRORS else "generic"
        for w in waiters:
            text = gettext(w.lang, f"err-{code}")
            if not await self.sender.edit_status(
                text, chat_id=w.target.chat_id, message_id=w.status_message_id
            ):
                try:
                    await self.sender.text(w.target, text)
                except Exception:
                    log.exception("could not report error to %s", w.target)

    async def _record(
        self,
        user_id: int | None,
        platform: str | None,
        key: str | None,
        method: str | None,
        error_code: str | None,
        egress: int,
        duration_ms: int,
    ) -> None:
        try:
            async with self.sm() as session:
                session.add(
                    Download(
                        user_id=user_id,
                        platform=platform,
                        key=key,
                        method=method,
                        status="error" if error_code else "ok",
                        error_class=error_code,
                        bytes_egress=egress,
                        duration_ms=duration_ms,
                    )
                )
                await session.commit()
        except Exception:
            log.exception("could not record download")
