"""Parallel big-file upload for Telethon.

Telethon's own upload sends one 512 KB part at a time, so a single high-latency link caps it
at ~1 MB/s. Here many parts are in flight at once (the connection pipelines requests)."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.upload import SaveBigFilePartRequest
from telethon.tl.types import InputFileBig

log = logging.getLogger(__name__)

PART_SIZE = 512 * 1024
WORKERS = 12
MIN_BIG = 10 * 1024 * 1024  # Telegram requires the "big file" API above 10 MB


async def fast_upload(client: TelegramClient, path: Path, workers: int = WORKERS) -> InputFileBig:
    size = os.path.getsize(path)
    parts = max(1, math.ceil(size / PART_SIZE))
    file_id = random.getrandbits(63)
    sem = asyncio.Semaphore(workers)
    tasks: list[asyncio.Task] = []

    async def send(index: int, data: bytes) -> None:
        try:
            for attempt in range(4):
                try:
                    if await client(SaveBigFilePartRequest(file_id, index, parts, data)):
                        return
                except Exception as exc:
                    if attempt == 3:
                        raise
                    log.warning("part %d/%d retry: %s", index, parts, exc)
                    await asyncio.sleep(1 + attempt)
            raise RuntimeError(f"Telegram rejected part {index}")
        finally:
            sem.release()

    try:
        with open(path, "rb") as fh:
            for index in range(parts):
                data = fh.read(PART_SIZE)
                await sem.acquire()
                tasks.append(asyncio.create_task(send(index, data)))
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return InputFileBig(file_id, parts, path.name)
