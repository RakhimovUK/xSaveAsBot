"""gallery-dl fallback: list direct media URLs of a post (images, carousels, slideshows)."""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlsplit

from app.extractors.base import MediaInfo, MediaItem
from app.extractors.errors import ExtractError, NotFoundError, classify

log = logging.getLogger(__name__)

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic"}
VIDEO_EXTS = {"mp4", "mov", "webm", "m4v"}


async def list_urls(url: str, timeout: int = 60) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "gallery_dl",
        "-g",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError as exc:
        proc.kill()
        raise classify("timed out") from exc
    lines = [ln.strip() for ln in out.decode(errors="replace").splitlines()]
    urls = [ln for ln in lines if ln.startswith("http")]
    if not urls:
        raise (
            classify(err.decode(errors="replace")[-300:] or "no media")
            if err
            else NotFoundError("no media")
        )
    return urls


def _kind(url: str) -> str:
    ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    return "photo"


async def probe(url: str, key: str, platform: str) -> MediaInfo:
    urls = await list_urls(url)
    items = [
        MediaItem(kind=_kind(u), url=u, ext=urlsplit(u).path.rsplit(".", 1)[-1].lower())
        for u in urls
    ]
    if not items:
        raise ExtractError("gallery-dl found nothing")
    return MediaInfo(platform=platform, key=key, source_url=url, items=items)
