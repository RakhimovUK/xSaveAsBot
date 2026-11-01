"""Phase 1 test commands: topic routing, arq round-trip and storage-channel round-trip."""

from __future__ import annotations

import html
import logging
import time
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from arq import ArqRedis

from app.bot.sender import Sender
from app.bot.targets import target_for_message
from app.config import Settings
from app.db.models import Group
from app.delivery.pending import PendingDelivery, add_waiter
from app.i18n import Translator
from app.queue import UPLOADER_QUEUE, WORKER_QUEUE

log = logging.getLogger(__name__)

router = Router(name="debug")
echo_router = Router(name="echo")


@router.message(Command("where"))
async def cmd_where(
    message: Message, sender: Sender, t: Translator, db_group: Group | None
) -> None:
    target = target_for_message(message, db_group)
    await sender.text(
        target,
        t(
            "where",
            chat_id=str(target.chat_id),
            thread=str(target.message_thread_id),
            reply_to=str(target.reply_to_message_id),
        ),
    )


@router.message(Command("ping"))
async def cmd_ping(
    message: Message,
    sender: Sender,
    t: Translator,
    arq: ArqRedis,
    settings: Settings,
    db_group: Group | None,
) -> None:
    target = target_for_message(message, db_group)
    if not settings.is_admin(message.from_user and message.from_user.id):
        await sender.text(target, t("admin-only"))
        return
    await sender.text(target, t("ping-sent"))
    started = time.monotonic()
    try:
        job = await arq.enqueue_job("ping", str(message.message_id), _queue_name=WORKER_QUEUE)
        result = await job.result(timeout=15)
    except Exception as exc:
        log.exception("ping failed")
        await sender.text(target, t("ping-fail", error=html.escape(repr(exc))))
        return
    ms = int((time.monotonic() - started) * 1000)
    await sender.text(target, t("ping-ok", result=html.escape(str(result)), ms=str(ms)))


@router.message(Command("testupload"))
async def cmd_testupload(
    message: Message,
    sender: Sender,
    t: Translator,
    lang: str,
    arq: ArqRedis,
    settings: Settings,
    db_group: Group | None,
) -> None:
    """Userbot posts a test photo to the storage channel; the channel_post handler
    then delivers it back here (same topic) via the pending-deliveries list."""
    target = target_for_message(message, db_group)
    user_id = message.from_user.id if message.from_user else None
    if not settings.is_admin(user_id):
        await sender.text(target, t("admin-only"))
        return
    key = f"test:{uuid.uuid4().hex[:12]}"
    await add_waiter(arq, key, PendingDelivery(target=target, lang=lang, user_id=user_id))
    await sender.text(target, t("testupload-sent"))
    try:
        job = await arq.enqueue_job(
            "upload_test_file", key, settings.storage_channel_default, _queue_name=UPLOADER_QUEUE
        )
        await job.result(timeout=90)
    except Exception as exc:
        log.exception("testupload failed")
        await sender.text(target, t("testupload-fail", error=html.escape(repr(exc))))


@router.message(Command("userbot"))
async def cmd_userbot(
    message: Message,
    sender: Sender,
    t: Translator,
    arq: ArqRedis,
    settings: Settings,
    db_group: Group | None,
) -> None:
    target = target_for_message(message, db_group)
    if not settings.is_admin(message.from_user and message.from_user.id):
        await sender.text(target, t("admin-only"))
        return
    try:
        job = await arq.enqueue_job("userbot_status", _queue_name=UPLOADER_QUEUE)
        status = await job.result(timeout=15)
    except Exception as exc:
        status = f"error: {exc!r}"
    await sender.text(target, t("userbot-status", status=html.escape(str(status))))


@echo_router.message(F.text & ~F.text.startswith("/"))
async def echo(message: Message, sender: Sender, t: Translator, db_group: Group | None) -> None:
    await sender.text(
        target_for_message(message, db_group), t("echo", text=html.escape(message.text or ""))
    )
