"""Benchmark helper bots through the uploader's `relay_probe` job (run inside the worker image).

    python scripts/bench_helpers.py out.json @bot1 @bot2 ...

Per helper: an Instagram reel, a YouTube link with the bot's default quality and, when the
bot handles YouTube, every quality button (360p/480p/720p/1080p/MP3) one after another.
Helpers run in parallel; results are written to out.json as they arrive."""

from __future__ import annotations

import asyncio
import json
import sys

from arq import create_pool

from app.config import get_settings
from app.queue import UPLOADER_QUEUE, redis_settings

IG_URL = "https://www.instagram.com/reel/De9oyINo2eW/"
YT_URL = "https://www.youtube.com/watch?v=Bqd6FC2xomU"
YT_VARIANTS = ["360p", "480p", "720p", "1080p", "mp3"]
PARALLEL = 8


def username_of(raw: str) -> str:
    return raw.strip().rstrip("/").split("/")[-1].lstrip("@")


async def run_probe(pool, user: str, url: str, variant: str | None, wants: str) -> dict:
    job = await pool.enqueue_job(
        "relay_probe", user, url, variant, wants, _queue_name=UPLOADER_QUEUE
    )
    try:
        return await job.result(timeout=240)
    except Exception as exc:
        return {"ok": False, "seconds": 240.0, "error": f"job: {exc!r}"}


async def bench_one(pool, user: str, results: dict, sem: asyncio.Semaphore, out: str) -> None:
    async with sem:
        entry: dict = {}
        results[user] = entry
        entry["instagram"] = await run_probe(pool, user, IG_URL, None, "video")
        entry["youtube_default"] = await run_probe(pool, user, YT_URL, None, "video")
        if entry["youtube_default"].get("ok"):
            for variant in YT_VARIANTS:
                wants = "audio" if variant == "mp3" else "video"
                entry[f"youtube_{variant}"] = await run_probe(pool, user, YT_URL, variant, wants)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print("done", user, flush=True)


async def main() -> None:
    out = sys.argv[1]
    users = [username_of(a) for a in sys.argv[2:]]
    pool = await create_pool(redis_settings(get_settings().redis_url))
    results: dict = {}
    sem = asyncio.Semaphore(PARALLEL)
    await asyncio.gather(*(bench_one(pool, u, results, sem, out) for u in users))
    print("ALL DONE", flush=True)


asyncio.run(main())
