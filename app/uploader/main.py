"""Uploader service: python -m app.uploader.main

The only process that holds userbot sessions. Consumes the uploader queue (upload a
file to a storage channel; later: relay, inbox downloads).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from arq import run_worker

from app.bot.media_utils import key_tag
from app.config import get_settings
from app.logging_setup import setup_logging
from app.media.testfile import write_png
from app.queue import UPLOADER_QUEUE, redis_settings
from app.uploader.userbot import UserbotPool

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    pool = UserbotPool(s.userbot_sessions, s.tg_api_id, s.tg_api_hash)
    await pool.start()
    ctx["userbots"] = pool


async def shutdown(ctx: dict[str, Any]) -> None:
    pool: UserbotPool | None = ctx.get("userbots")
    if pool is not None:
        await pool.stop()


async def upload_test_file(ctx: dict[str, Any], key: str, channel_id: int) -> int:
    """Post a generated PNG with the #key tag; the bot picks it up as channel_post."""
    client = ctx["userbots"].get()
    with tempfile.TemporaryDirectory(prefix="xsaveasbot-") as tmp:
        path = write_png(Path(tmp) / "xsaveasbot-test.png")
        msg = await client.send_file(channel_id, str(path), caption=key_tag(key))
    log.info("Uploaded test file key=%s channel=%s msg=%s", key, channel_id, msg.id)
    return msg.id


async def userbot_status(ctx: dict[str, Any]) -> str:
    pool: UserbotPool = ctx["userbots"]
    states = []
    for name, client in zip(pool.names, pool.clients, strict=True):
        states.append(f"{name}={'online' if client.is_connected() else 'offline'}")
    return ", ".join(states)


class UploaderSettings:
    functions = [upload_test_file, userbot_status]
    queue_name = UPLOADER_QUEUE
    on_startup = startup
    on_shutdown = shutdown


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    run_worker(
        UploaderSettings,  # type: ignore[arg-type]
        redis_settings=redis_settings(settings.redis_url),
        max_jobs=settings.uploader_concurrency,
    )


if __name__ == "__main__":
    main()
