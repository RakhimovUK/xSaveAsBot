"""Title/channel of a YouTube video via oEmbed (works from IPs that yt-dlp is blocked on)."""

from __future__ import annotations

import html
import logging

import httpx

log = logging.getLogger(__name__)

OEMBED = "https://www.youtube.com/oembed"


async def fetch_oembed(url: str) -> dict[str, str] | None:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(OEMBED, params={"url": url, "format": "json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.info("oembed failed for %s: %s", url, exc)
        return None
    title = (data.get("title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "author": (data.get("author_name") or "").strip(),
        "author_url": (data.get("author_url") or "").strip(),
    }


def caption_html(url: str, meta: dict[str, str]) -> str:
    """`📹 Title → link` / `👤 #Channel → link` (HTML, ready for parse_mode=HTML)."""
    lines = [f'📹 <a href="{html.escape(url, quote=True)}">{html.escape(meta["title"])}</a>']
    author = meta.get("author")
    if author:
        tag = "#" + "_".join(author.split())
        if meta.get("author_url"):
            lines.append(
                f'👤 <a href="{html.escape(meta["author_url"], quote=True)}">{html.escape(tag)}</a>'
            )
        else:
            lines.append(f"👤 {html.escape(tag)}")
    return "\n".join(lines)
