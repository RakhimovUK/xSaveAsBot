"""Bot entrypoint: python -m app.bot.main"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq import create_pool

from app.bot.middlewares.context import ContextMiddleware
from app.bot.routers import admin, debug, links, start, storage_posts
from app.bot.sender import Sender
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging_setup import setup_logging
from app.queue import redis_settings

log = logging.getLogger(__name__)


def build_dispatcher(echo: bool) -> Dispatcher:
    dp = Dispatcher()
    dp.include_routers(storage_posts.router, start.router, debug.router, admin.router, links.router)
    # Last: plain text without a link (echo is a Phase 1 test aid, off in production)
    dp.include_router(debug.echo_router if echo else links.fallback_router)
    return dp


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    engine = make_engine(settings.database_url)
    arq_redis = await create_pool(redis_settings(settings.redis_url))

    dp = build_dispatcher(settings.feature_echo)
    dp.update.outer_middleware(ContextMiddleware(make_sessionmaker(engine), settings))
    dp["settings"] = settings
    dp["sender"] = Sender(bot)
    dp["arq"] = arq_redis

    me = await bot.get_me()
    dp["bot_username"] = me.username
    log.info("Bot @%s started, storage channels=%s", me.username, settings.all_storage_channel_ids)
    try:
        if settings.mode == "webhook":
            raise NotImplementedError("Webhook mode arrives in Phase 9; use MODE=polling")
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await arq_redis.aclose()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
