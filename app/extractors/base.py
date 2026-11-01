"""Shared extractor data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MediaItem:
    kind: str  # video | photo | audio | animation | document
    url: str | None = None  # direct CDN URL when a single plain file (url-send possible)
    ext: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None


@dataclass
class FormatOption:
    """A YouTube picker choice."""

    variant: str  # "720p"
    height: int
    size: int | None


@dataclass
class MediaInfo:
    platform: str
    key: str
    source_url: str
    title: str | None = None
    caption: str | None = None
    uploader: str | None = None
    duration: float | None = None
    items: list[MediaItem] = field(default_factory=list)
    formats: list[FormatOption] = field(default_factory=list)
    raw: dict[str, Any] | None = None

    @property
    def total_size(self) -> int | None:
        sizes = [i.size for i in self.items]
        if not sizes or any(s is None for s in sizes):
            return None
        return sum(s for s in sizes if s)

    @property
    def all_direct(self) -> bool:
        return bool(self.items) and all(i.url for i in self.items)


@dataclass
class LocalFile:
    """A downloaded file, ready for the uploader."""

    path: str
    kind: str
    name: str
    size: int = 0
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    title: str | None = None
    performer: str | None = None
    thumb: str | None = None
