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


HEIGHT_RE = re.compile(r"(?<!\d)(\d{3,4})p\b")
# Buttons that never lead to the video itself
# Paid buttons (Telegram Stars etc.) must never be pressed, for any variant
PAYMENT_MARKERS = ("⭐", "pay", "balans", "stars", "оплат", "купить", "buy", "to'lov", "premium")
AVOID_FOR_VIDEO = (
    *AUDIO_PREFS,
    "превью",
    "preview",
    "обрезк",
    "trim",
    "текст",
    "text",
    "перейти",
    "channel",
    "subscribed",
)
DEFAULT_MAX_HEIGHT = 720  # a sensible quality/size trade-off when no height is requested


def choose_button(rows: list[list[Any]], variant: str | None) -> tuple[int, int] | None:
    """Pick the inline button for the wanted variant. URL buttons are never clicked.

    Returns None when nothing suitable exists (better to wait/fail than to click
    "Audio" for a video or an unrelated "Preview"/"Trim" button)."""
    clickable = [
        (i, j, (getattr(b, "text", "") or "").lower())
        for i, row in enumerate(rows)
        for j, b in enumerate(row)
        if not getattr(b, "url", None)
        and not any(m in (getattr(b, "text", "") or "").lower() for m in PAYMENT_MARKERS)
    ]
    if variant == "mp3":
        for pref in AUDIO_PREFS:
            for i, j, text in clickable:
                if pref in text:
                    return i, j
        return None

    usable = [c for c in clickable if not any(word in c[2] for word in AVOID_FOR_VIDEO)]
    heights = sorted(
        (int(m.group(1)), i, j) for i, j, text in usable if (m := HEIGHT_RE.search(text))
    )
    if heights:
        want = DEFAULT_MAX_HEIGHT
        if variant and variant.endswith("p") and variant[:-1].isdigit():
            want = int(variant[:-1])
        not_above = [h for h in heights if h[0] <= want]
        _, i, j = not_above[-1] if not_above else heights[0]
        return i, j
    for pref in ("video", "видео", "mp4", "best", "лучш", "download", "скачать", "yuklab"):
        for i, j, text in usable:
            if pref in text:
                return i, j
    return (usable[0][0], usable[0][1]) if usable else None


LANG_BUTTON_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}\s*[A-Z]{2,3}\b")
CURRENT_MARKS = ("🚀", "✅", "☑", "✔", "●")


def choose_language(rows: list[list[Any]]) -> tuple[int, int] | None:
    """An audio-language menu ("choose the dubbing language"): press the currently marked
    language (the default track), else English. None when the message is not such a menu."""
    langs = [
        (i, j, getattr(b, "text", "") or "")
        for i, row in enumerate(rows)
        for j, b in enumerate(row)
        if not getattr(b, "url", None) and LANG_BUTTON_RE.search(getattr(b, "text", "") or "")
    ]
    if len(langs) < 3:
        return None
    for i, j, text in langs:
        if any(mark in text for mark in CURRENT_MARKS):
            return i, j
    for i, j, text in langs:
        if text.strip().endswith("EN"):
            return i, j
    return langs[0][0], langs[0][1]


def is_url_language_menu(rows: list[list[Any]]) -> bool:
    """A language menu made of URL (mini-app) buttons: the userbot cannot press those."""
    urls = [
        b
        for row in rows
        for b in row
        if getattr(b, "url", None) and LANG_BUTTON_RE.search(getattr(b, "text", "") or "")
    ]
    return len(urls) >= 3


def back_button(rows: list[list[Any]]) -> tuple[int, int] | None:
    for i, row in enumerate(rows):
        for j, b in enumerate(row):
            text = (getattr(b, "text", "") or "").lower()
            if not getattr(b, "url", None) and any(w in text for w in ("назад", "back", "orqaga")):
                return i, j
    return None


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
