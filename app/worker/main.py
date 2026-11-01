"""Download/probe worker: python -m app.worker.main

Phase 1 only has `ping` (arq round-trip). Never opens the userbot session: anything
that needs MTProto is enqueued to the uploader.
"""

from __future__ import annotations

import socket
from typing import Any

from arq import run_worker

from app.config import get_settings
from app.logging_setup import setup_logging
from app.queue import WORKER_QUEUE, redis_settings


async def ping(ctx: dict[str, Any], payload: str) -> str:
    return f"pong:{payload}@{socket.gethostname()}"


class WorkerSettings:
    functions = [ping]
    queue_name = WORKER_QUEUE


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
