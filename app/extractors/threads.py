"""Threads: best-effort parser of the media JSON embedded in the post page.

Threads has no stable public API and yt-dlp does not support it, so this reads the
`video_versions` / `image_versions2` blocks from the HTML. It is isolated here so a
layout change only breaks this module; the chain falls back to gallery-dl, then relay.
"""

from __future__ import annotations

import html as html_lib
import json
import re

import httpx

from app.extractors.base import MediaInfo, MediaItem
from app.extractors.errors import NotFoundError, TemporaryError, UnsupportedError
from app.extractors.url_utils import UA

VIDEO_RE = re.compile(r'"video_versions":\[(\{.*?\})\]', re.S)
IMAGE_RE = re.compile(r'"image_versions2":\{"candidates":\[(\{.*?\})\]', re.S)
URL_RE = re.compile(r'"url":"(https:[^"]+)"')
WIDTH_RE = re.compile(r'"width":(\d+)')
HEIGHT_RE = re.compile(r'"height":(\d+)')
DESC_RE = re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"')


def _unescape(url: str) -> str:
    try:
        return json.loads(f'"{url}"')
    except ValueError:
        return url.replace("\\u0026", "&").replace("\\/", "/")


def parse_page(page: str, code: str) -> list[MediaItem]:
    anchor = page.find(f'"code":"{code}"')
    window = page[anchor : anchor + 80000] if anchor >= 0 else page
    images = [(m.start(), m.group(1)) for m in IMAGE_RE.finditer(window)]
    videos = [(m.start(), m.group(1)) for m in VIDEO_RE.finditer(window)]
    items: list[MediaItem] = []
    for idx, (pos, block) in enumerate(images):
        next_pos = images[idx + 1][0] if idx + 1 < len(images) else len(window)
        video = next((b for p, b in videos if pos <= p < next_pos), None)
        chosen = video or block
        url_match = URL_RE.search(chosen)
        if not url_match:
            continue
        width = WIDTH_RE.search(block)
        height = HEIGHT_RE.search(block)
        items.append(
            MediaItem(
                kind="video" if video else "photo",
                url=_unescape(url_match.group(1)),
                ext="mp4" if video else "jpg",
                width=int(width.group(1)) if width else None,
                height=int(height.group(1)) if height else None,
            )
        )
    # Videos without a poster image block
    if not items:
        for _, block in videos:
            url_match = URL_RE.search(block)
            if url_match:
                items.append(MediaItem(kind="video", url=_unescape(url_match.group(1)), ext="mp4"))
    return items


async def probe(url: str, key: str) -> MediaInfo:
    code = key.split(":", 1)[1]
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=20, headers={"User-Agent": UA, "Accept-Language": "en"}
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise TemporaryError(str(exc)) from exc
    if resp.status_code == 404:
        raise NotFoundError("threads post not found")
    if resp.status_code >= 400:
        raise TemporaryError(f"threads http {resp.status_code}")
    items = parse_page(resp.text, code)
    if not items:
        raise UnsupportedError("threads media not found in page")
    desc = DESC_RE.search(resp.text)
    caption = html_lib.unescape(desc.group(1)) if desc else None
    return MediaInfo(
        platform="threads", key=key, source_url=url, title=caption, caption=caption, items=items
    )
