"""Link handling: validate, rate-limit, enqueue. Handlers never block (brief section 5)."""

from __future__ import annotations

import re
import time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis

from app.bot.sender import Sender
from app.bot.targets import target_for_callback, target_for_message
from app.config import Settings
from app.db.models import Group, User
from app.delivery.jobs import LinkJob
from app.extractors.url_utils import detect, find_urls
from app.i18n import Translator
from app.queue import WORKER_QUEUE

router = Router(name="links")
fallback_router = Router(name="fallback")

MAX_LINKS_PER_MESSAGE = 3
VARIANT_RE = re.compile(r"^(?:\d{3,4}p|mp3|best)$")


class HasUrl(Filter):
    async def __call__(self, message: Message) -> bool | dict[str, list[str]]:
        urls = find_urls(message.text or message.caption)
        return {"urls": urls} if urls else False


def group_allows(message: Message, group: Group | None) -> bool:
    """Per-group settings: auto-download switch and allowed topics (0 = General)."""
    if group is None:
        return True
    if not group.auto_download:
        return False
    if group.allowed_topics is not None:
        thread = message.message_thread_id if message.is_topic_message else 0
        return thread in group.allowed_topics
    return True


async def rate_limited(redis: ArqRedis, settings: Settings, user_id: int | None) -> bool:
    if user_id is None:
        return False
    key = f"xsaveasbot:rl:{user_id}:{int(time.time() // 60)}"
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, 120)
    return count > settings.user_rate_limit


@router.message(HasUrl())
async def on_links(
    message: Message,
    urls: list[str],
    sender: Sender,
    t: Translator,
    lang: str,
    arq: ArqRedis,
    settings: Settings,
    db_user: User | None,
    db_group: Group | None,
) -> None:
    if db_user is not None and db_user.is_banned:
        return
    private = message.chat.type == ChatType.PRIVATE
    if not private and not group_allows(message, db_group):
        return
    target = target_for_message(message, db_group)

    links = []
    for url in urls:
        det = detect(url)
        if det is not None and det.platform in settings.platforms_enabled:
            links.append(url)
    if not links:
        if private:
            await sender.text(target, t("unsupported-link"))
        return  # in groups unsupported links are ignored silently

    user_id = message.from_user.id if message.from_user else None
    if await rate_limited(arq, settings, user_id):
        await sender.text(target, t("err-ratelimit"))
        return
    for url in links[:MAX_LINKS_PER_MESSAGE]:
        status = await sender.text(target, t("status-analyzing"))
        job = LinkJob.create(url, target, lang, user_id, status.message_id)
        await arq.enqueue_job("process_link", job.to_dict(), _queue_name=WORKER_QUEUE)


@router.callback_query(F.data.startswith("yv:"))
async def on_quality_picked(
    callback: CallbackQuery,
    sender: Sender,
    t: Translator,
    lang: str,
    arq: ArqRedis,
    db_group: Group | None,
) -> None:
    """YouTube picker button: continue in the topic of the keyboard message."""
    parts = (callback.data or "").split(":", 2)
    msg = callback.message
    if (
        len(parts) != 3
        or not re.fullmatch(r"[\w-]{11}", parts[1])
        or not VARIANT_RE.match(parts[2])
        or not isinstance(msg, Message)
    ):
        await callback.answer()
        return
    _, video_id, variant = parts
    target = target_for_callback(callback, db_group)
    await sender.edit_status(t("status-analyzing"), chat_id=msg.chat.id, message_id=msg.message_id)
    job = LinkJob.create(
        f"https://www.youtube.com/watch?v={video_id}",
        target,
        lang,
        callback.from_user.id,
        msg.message_id,
        variant,
    )
    await arq.enqueue_job("process_link", job.to_dict(), _queue_name=WORKER_QUEUE)
    await callback.answer()


@fallback_router.message(F.text & ~F.text.startswith("/") & (F.chat.type == ChatType.PRIVATE))
async def send_link_hint(
    message: Message, sender: Sender, t: Translator, db_group: Group | None
) -> None:
    await sender.text(target_for_message(message, db_group), t("send-link-hint"))
