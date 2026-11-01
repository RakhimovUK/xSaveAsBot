"""Build ReplyTargets with the group's fallback setting applied."""

from aiogram.types import CallbackQuery, Message

from app.bot.reply_target import ReplyTarget
from app.db.models import Group


def target_for_message(message: Message, db_group: Group | None) -> ReplyTarget:
    fallback = bool(db_group and db_group.fallback_without_thread)
    return ReplyTarget.from_message(message, fallback_without_thread=fallback)


def target_for_callback(callback: CallbackQuery, db_group: Group | None) -> ReplyTarget:
    fallback = bool(db_group and db_group.fallback_without_thread)
    return ReplyTarget.from_callback(callback, fallback_without_thread=fallback)
