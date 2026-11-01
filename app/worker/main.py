"""Download/probe worker: python -m app.worker.main

Runs the delivery ladder (`process_link`). It never opens the userbot session: anything
that needs MTProto (uploads, relay) is enqueued to the uploader.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from arq import run_worker

from app.bot.sender import Sender
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.delivery.jobs import LinkJob
from app.delivery.ladder import Processor
from app.logging_setup import setup_logging
from app.queue import WORKER_QUEUE, redis_settings

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    bot = Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    engine = make_engine(s.database_url)
    ctx["bot"] = bot
    ctx["engine"] = engine
    ctx["processor"] = Processor(
        settings=s,
        redis=ctx["redis"],
        sessionmaker=make_sessionmaker(engine),
        sender=Sender(bot),
        bot_username=me.username,
    )
    log.info("Worker ready as helper of @%s", me.username)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["bot"].session.close()
    await ctx["engine"].dispose()


async def ping(ctx: dict[str, Any], payload: str) -> str:
    return f"pong:{payload}@{socket.gethostname()}"


async def process_link(ctx: dict[str, Any], job: dict[str, Any]) -> None:
    await ctx["processor"].run(LinkJob.from_dict(job))


class WorkerSettings:
    functions = [ping, process_link]
    queue_name = WORKER_QUEUE
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 7200
    max_tries = 1
    keep_result = 300


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    run_worker(
        WorkerSettings,  # type: ignore[arg-type]
        redis_settings=redis_settings(settings.redis_url),
        max_jobs=settings.worker_concurrency,
    )


if __name__ == "__main__":
    main()
