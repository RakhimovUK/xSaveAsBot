from __future__ import annotations

import re
from dataclasses import dataclass

from aiogram.types import Message

# Machine-readable tag in every storage post caption, e.g. "#key yt:dQw4w9WgXcQ:720p"
KEY_RE = re.compile(r"#key\s+(\S+)")


def parse_key(caption: str | None) -> str | None:
    if not caption:
        return None
    match = KEY_RE.search(caption)
    return match.group(1) if match else None


PART_RE = re.compile(r"#part\s+(\d+)/(\d+)")


def key_tag(key: str, index: int = 1, total: int = 1) -> str:
    """Caption tag of a storage post: `#key <cache-key> #part i/n` (albums = several posts)."""
    return f"#key {key} #part {index}/{total}"


def parse_part(caption: str | None) -> tuple[int, int]:
    match = PART_RE.search(caption or "")
    return (int(match.group(1)), int(match.group(2))) if match else (1, 1)


@dataclass(frozen=True, slots=True)
class StoredFile:
    kind: str  # photo | video | animation | audio | voice | video_note | document
    file_id: str
    file_unique_id: str
    size: int | None


def extract_file(message: Message) -> StoredFile | None:
    if message.photo:
        p = message.photo[-1]  # largest size
        return StoredFile("photo", p.file_id, p.file_unique_id, p.file_size)
    # animation before document: GIFs carry both fields
    for kind in ("video", "animation", "audio", "voice", "video_note", "document"):
        obj = getattr(message, kind)
        if obj is not None:
            return StoredFile(kind, obj.file_id, obj.file_unique_id, obj.file_size)
    return None
