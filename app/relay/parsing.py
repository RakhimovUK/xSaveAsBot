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


def classify_message(msg: Any) -> str:
    """media | junk | error | buttons | progress"""
    media = getattr(msg, "media", None)
    if media is not None and type(media).__name__ != "MessageMediaWebPage":
        return "media"
    text = (getattr(msg, "message", "") or "").lower()
    if any(marker in text for marker in JOIN_MARKERS):
        return "junk"
    if any(marker in text for marker in ERROR_MARKERS):
        return "error"
    if getattr(msg, "buttons", None):
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
