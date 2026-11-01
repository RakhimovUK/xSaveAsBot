"""Uploader service: python -m app.uploader.main

The only process that holds userbot sessions. Consumes the uploader queue:
upload files to a storage channel, relay through helper bots, test upload.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from arq import run_worker
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from app.bot.media_utils import key_tag
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging_setup import setup_logging
from app.media.testfile import write_png
from app.queue import UPLOADER_QUEUE, redis_settings
from app.uploader.relay import relay_fetch
from app.uploader.userbot import UserbotPool

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    pool = UserbotPool(s.userbot_sessions, s.tg_api_id, s.tg_api_hash)
    await pool.start()
    ctx["userbots"] = pool
    ctx["settings"] = s
    ctx["engine"] = make_engine(s.database_url)
    ctx["sessionmaker"] = make_sessionmaker(ctx["engine"])


async def shutdown(ctx: dict[str, Any]) -> None:
    pool: UserbotPool | None = ctx.get("userbots")
    if pool is not None:
        await pool.stop()
    if (engine := ctx.get("engine")) is not None:
        await engine.dispose()


async def upload_test_file(ctx: dict[str, Any], key: str, channel_id: int) -> int:
    """Post a generated PNG with the #key tag; the bot picks it up as channel_post."""
    client = ctx["userbots"].get()
    with tempfile.TemporaryDirectory(prefix="xsaveasbot-") as tmp:
        path = write_png(Path(tmp) / "xsaveasbot-test.png")
        msg = await client.send_file(channel_id, str(path), caption=key_tag(key))
    log.info("Uploaded test file key=%s channel=%s msg=%s", key, channel_id, msg.id)
    return msg.id


def _attributes(f: dict[str, Any]) -> list[Any] | None:
    duration = int(f.get("duration") or 0)
    if f["kind"] == "video":
        return [
            DocumentAttributeVideo(
                duration=duration,
                w=int(f.get("width") or 0),
                h=int(f.get("height") or 0),
                supports_streaming=True,
            )
        ]
    if f["kind"] == "audio":
        return [
            DocumentAttributeAudio(
                duration=duration, title=f.get("title"), performer=f.get("performer")
            )
        ]
    return None


async def upload_files(
    ctx: dict[str, Any], key: str, channel_id: int, files: list[dict[str, Any]]
) -> dict[str, Any]:
    """Self-download path: upload local files (shared jobs dir) to the storage channel,
    one tagged post per file so albums can be reassembled by the bot."""
    client = ctx["userbots"].get()
    total = len(files)
    try:
        for index, f in enumerate(files, 1):
            path = Path(f["path"])
            if f.get("name") and f["name"] != path.name:
                path = path.rename(path.with_name(f["name"]))
            await client.send_file(
                channel_id,
                str(path),
                caption=key_tag(key, index, total),
                attributes=_attributes(f),
                supports_streaming=f["kind"] == "video",
            )
    except Exception as exc:
        log.exception("upload_files failed key=%s", key)
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    log.info("Uploaded %d file(s) key=%s channel=%s", total, key, channel_id)
    return {"ok": True, "parts": total}


async def userbot_status(ctx: dict[str, Any]) -> str:
    pool: UserbotPool = ctx["userbots"]
    states = []
    for name, client in zip(pool.names, pool.clients, strict=True):
        states.append(f"{name}={'online' if client.is_connected() else 'offline'}")
    return ", ".join(states)


class UploaderSettings:
    functions = [upload_test_file, upload_files, relay_fetch, userbot_status]
    queue_name = UPLOADER_QUEUE
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 3600
    max_tries = 1
    keep_result = 600


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
