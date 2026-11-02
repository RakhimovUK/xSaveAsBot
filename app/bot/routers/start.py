from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.sender import Sender
from app.bot.targets import target_for_callback, target_for_message
from app.config import SUPPORTED_LANGS
from app.db import repo
from app.db.models import Group, User
from app.delivery.jobs import LinkJob
from app.i18n import Translator, gettext
from app.queue import WORKER_QUEUE

router = Router(name="start")


def lang_keyboard() -> InlineKeyboardMarkup:
    flags = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{flags[code]} {gettext(code, 'lang-name')}", callback_data=f"lang:{code}"
                )
                for code in SUPPORTED_LANGS
            ]
        ]
    )


def _welcome(t: Translator, first_name: str | None) -> str:
    return t("welcome", name=html.escape(first_name or ""))


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    sender: Sender,
    t: Translator,
    lang: str,
    arq: ArqRedis,
    db_user: User | None,
    db_group: Group | None,
) -> None:
    target = target_for_message(message, db_group)
    arg = command.args or ""
    if arg.startswith("yt_") and re.fullmatch(r"[A-Za-z0-9_-]{11}", arg[3:]):
        # deep link from a caption's "more formats": open the YouTube picker
        status = await sender.text(target, t("status-analyzing"))
        job = LinkJob.create(
            f"https://www.youtube.com/watch?v={arg[3:]}",
            target,
            lang,
            message.from_user.id if message.from_user else None,
            status.message_id,
        )
        await arq.enqueue_job("process_link", job.to_dict(), _queue_name=WORKER_QUEUE)
        return
    if db_user is not None and db_user.lang is None:
        await sender.text(target, t("lang-pick"), reply_markup=lang_keyboard())
        return
    name = message.from_user.first_name if message.from_user else None
    await sender.text(target, _welcome(t, name))


@router.message(Command("lang"))
async def cmd_lang(message: Message, sender: Sender, t: Translator, db_group: Group | None) -> None:
    await sender.text(
        target_for_message(message, db_group), t("lang-pick"), reply_markup=lang_keyboard()
    )


@router.message(Command("help"))
async def cmd_help(message: Message, sender: Sender, t: Translator, db_group: Group | None) -> None:
    await sender.text(target_for_message(message, db_group), t("help"))


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(
    callback: CallbackQuery,
    sender: Sender,
    session: AsyncSession,
    db_user: User | None,
    db_group: Group | None,
) -> None:
    code = (callback.data or "").split(":", 1)[1]
    if code not in SUPPORTED_LANGS or db_user is None:
        await callback.answer()
        return
    first_time = db_user.lang is None
    await repo.set_user_lang(session, db_user.tg_id, code)
    t = Translator(code)
    await callback.answer(t("lang-changed"))
    msg = callback.message
    if isinstance(msg, Message):
        await sender.edit_text(t("lang-changed"), chat_id=msg.chat.id, message_id=msg.message_id)
    if first_time:
        await sender.text(
            target_for_callback(callback, db_group), _welcome(t, callback.from_user.first_name)
        )
