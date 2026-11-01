"""Per-update context: DB session, user/group upsert, language and translator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Chat, TelegramObject, User
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db import repo
from app.i18n import Translator, normalize_lang

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


class ContextMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker: async_sessionmaker, settings: Settings) -> None:
        self.sessionmaker = sessionmaker
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: User | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")

        async with self.sessionmaker() as session:
            db_user = None
            lang = self.settings.default_lang
            if tg_user is not None and not tg_user.is_bot:
                db_user = await repo.touch_user(session, tg_user.id, tg_user.username)
                lang = db_user.lang or normalize_lang(
                    tg_user.language_code, self.settings.default_lang
                )
            db_group = None
            if chat is not None and chat.type in GROUP_TYPES:
                db_group = await repo.touch_group(session, chat.id, chat.title, bool(chat.is_forum))

            data["session"] = session
            data["db_user"] = db_user
            data["db_group"] = db_group
            data["lang"] = lang
            data["t"] = Translator(lang)
            result = await handler(event, data)
            await session.commit()
            return result
