"""media_cache access: finished deliveries keyed by canonical media key."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaCache


@dataclass(frozen=True, slots=True)
class StoredPart:
    kind: str
    file_id: str
    file_unique_id: str
    size: int | None
    chat_id: int
    message_id: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CachedMedia:
    key: str
    caption: str | None
    parts: list[StoredPart]


async def cached_keys(session: AsyncSession, keys: list[str]) -> set[str]:
    """Which of `keys` are already cached (no hit counting): those are delivered instantly."""
    rows = await session.scalars(select(MediaCache.key).where(MediaCache.key.in_(keys)))
    return set(rows)


async def get_entry(session: AsyncSession, key: str) -> CachedMedia | None:
    row = await session.scalar(select(MediaCache).where(MediaCache.key == key))
    if row is None or not row.bot_file_ids:
        return None
    parts = [StoredPart(**p) for p in row.bot_file_ids]
    await session.execute(
        update(MediaCache).where(MediaCache.id == row.id).values(hits=MediaCache.hits + 1)
    )
    return CachedMedia(key=key, caption=row.caption, parts=parts)


async def save_entry(
    session: AsyncSession,
    key: str,
    platform: str,
    parts: list[StoredPart],
    caption: str | None,
) -> None:
    kind = "album" if len(parts) > 1 else parts[0].kind
    size = sum(p.size or 0 for p in parts) or None
    row = await session.scalar(select(MediaCache).where(MediaCache.key == key))
    if row is None:
        row = MediaCache(key=key)
        session.add(row)
    row.platform = platform
    row.kind = kind
    row.bot_file_ids = [p.to_dict() for p in parts]
    row.storage_channel_id = parts[0].chat_id
    row.storage_message_ids = [p.message_id for p in parts]
    row.caption = caption
    row.size = size
    await session.flush()
