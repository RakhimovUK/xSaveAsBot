"""Pure helpers to read a helper bot's replies (no Telegram I/O, easy to test)."""

from __future__ import annotations

import re
from typing import Any

JOIN_MARKERS = (
    "subscribe",
    "подпис",
    "подпиш",
    "join our",
    "join the",
    "вступи",
    "obuna",
    "a'zo bo'l",
    "must be a member",
)
ERROR_MARKERS = (
    "error",
    "ошибк",
    "не удалось",
    "не найден",
    "not found",
    "private",
    "приватн",
    "unavailable",
    "недоступ",
    "failed",
    "too large",
    "слишком",
    "xatolik",
    "topilmadi",
    "unsupported",
    "не поддерж",
)

VIDEO_PREFS = ("1080", "720", "best", "лучш", "mp4", "video", "видео")
AUDIO_PREFS = ("mp3", "audio", "аудио", "music", "музык")


VIDEO_ONLY_PLATFORMS = {"youtube", "vimeo", "twitch"}


def wanted_kind(platform: str, variant: str | None) -> str:
    """What the final media must be: audio (MP3), video (video sites) or any."""
    if variant == "mp3":
        return "audio"
    return "video" if platform in VIDEO_ONLY_PLATFORMS else "any"


def _is_photo(msg: Any) -> bool:
    return type(getattr(msg, "media", None)).__name__ == "MessageMediaPhoto"


def media_matches(msg: Any, wants: str) -> bool:
    """Is this media the kind we asked for? (A video site's thumbnail photo is not.)"""
    if wants == "any":
        return True
    mime = (getattr(getattr(msg, "file", None), "mime_type", None) or "").lower()
    if wants == "video":
        return mime.startswith("video/") or bool(
            getattr(msg, "video", None) or getattr(msg, "gif", None)
        )
    return mime.startswith("audio/") or bool(
        getattr(msg, "audio", None) or getattr(msg, "voice", None)
    )


def classify_message(msg: Any, wants: str = "any") -> str:
    """media | junk | error | buttons | progress"""
    media = getattr(msg, "media", None)
    has_buttons = bool(getattr(msg, "buttons", None))
    if media is not None and type(media).__name__ != "MessageMediaWebPage":
        # A photo carrying buttons is a quality prompt, not the result
        if media_matches(msg, wants) and not (_is_photo(msg) and has_buttons):
            return "media"
        return "buttons" if has_buttons else "progress"  # e.g. a thumbnail while processing
    text = (getattr(msg, "message", "") or "").lower()
    if any(marker in text for marker in JOIN_MARKERS):
        return "junk"
    if any(marker in text for marker in ERROR_MARKERS):
        return "error"
    if has_buttons:
        return "buttons"
    return "progress"


def choose_button(rows: list[list[Any]], variant: str | None) -> tuple[int, int] | None:
    """Pick the inline button matching the wanted variant; skip URL buttons."""
    prefs: tuple[str, ...]
    if variant == "mp3":
        prefs = AUDIO_PREFS
    elif variant and variant.endswith("p") and variant[:-1].isdigit():
        prefs = (variant[:-1], *VIDEO_PREFS)
    else:
        prefs = VIDEO_PREFS
    clickable = [
        (i, j, (getattr(b, "text", "") or "").lower())
        for i, row in enumerate(rows)
        for j, b in enumerate(row)
        if not getattr(b, "url", None)
    ]
    for pref in prefs:
        for i, j, text in clickable:
            if re.search(re.escape(pref), text):
                return i, j
    return (clickable[0][0], clickable[0][1]) if clickable else None


def media_plausible(msg: Any, expected_duration: float | None) -> bool:
    """Reject ads / wrong videos: duration must be near the one we probed (when known)."""
    file = getattr(msg, "file", None)
    duration = getattr(file, "duration", None)
    if (
        expected_duration
        and duration
        and abs(duration - expected_duration) > max(8.0, 0.3 * expected_duration)
    ):
        return False
    size = getattr(file, "size", None)
    return not (size is not None and size <= 0)
