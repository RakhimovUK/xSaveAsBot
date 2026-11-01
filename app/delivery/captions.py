"""Caption the user sees under delivered media (built fresh; never copied from helper bots)."""

from __future__ import annotations

import html

CAPTION_LIMIT = 1024


def build_caption(
    original: str | None,
    source_url: str | None,
    bot_username: str | None,
    ad: str | None = None,
    limit: int = CAPTION_LIMIT,
) -> str:
    footer_parts: list[str] = []
    if source_url:
        footer_parts.append(f'<a href="{html.escape(source_url, quote=True)}">🔗</a>')
    if bot_username:
        footer_parts.append(f"@{bot_username}")
    footer = " ".join(footer_parts)
    if ad:
        footer = f"{footer}\n{ad}" if footer else ad
    sep = "\n\n" if footer else ""
    available = limit - len(sep) - len(footer)
    text = (original or "").strip()
    if not text or available <= 10:
        return footer[:limit]
    text = text[: available - 1]
    while len(html.escape(text, quote=False)) > available and text:
        text = text[: max(0, len(text) - 20)]
    if len(text) < len((original or "").strip()):
        text = text.rstrip() + "…"
    return f"{html.escape(text, quote=False)}{sep}{footer}"
