"""YouTube caption pieces: oEmbed (works from IPs yt-dlp is blocked on) and the caption template."""

from __future__ import annotations

import html
import logging
import re

import httpx

log = logging.getLogger(__name__)

OEMBED = "https://www.youtube.com/oembed"
FLAG_RE = re.compile(r"([\U0001F1E6-\U0001F1FF]{2})\s+([A-Z]{2,3})\b")


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


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def caption_html(url: str, meta: dict[str, str]) -> str:
    """`📹 Title →` and `👤 #Channel →`; the whole text is the link (HTML)."""
    lines = [f"📹 {_link(url, meta['title'] + ' →')}"]
    author = meta.get("author")
    if author:
        tag = "#" + "_".join(author.split()) + " →"
        lines.append(
            f"👤 {_link(meta['author_url'], tag)}"
            if meta.get("author_url")
            else f"👤 {html.escape(tag)}"
        )
    return "\n".join(lines)


def footer_html(
    bot_username: str | None,
    key: str,
    quality: str | None,
    flag: str | None,
    more_text: str,
) -> str:
    """`@bot: 📹720p 🇺🇸 EN · more formats →` (the last part opens the picker in the bot)."""
    parts = []
    if quality:
        parts.append(html.escape(quality))
    if flag:
        parts.append(html.escape(flag))
    info = " ".join(parts)
    video_id = key.split(":")[1] if key.count(":") >= 1 else ""
    more = (
        _link(f"https://t.me/{bot_username}?start=yt_{video_id}", more_text)
        if bot_username and video_id
        else ""
    )
    tail = " · ".join(x for x in (info, more) if x)
    head = f"@{bot_username}" if bot_username else ""
    return f"{head}: {tail}" if head and tail else head or tail


def flag_from_text(text: str | None) -> str | None:
    m = FLAG_RE.search(text or "")
    return f"{m.group(1)} {m.group(2)}" if m else None
