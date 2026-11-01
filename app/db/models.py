"""ORM models. Phase 1 creates users, groups, media_cache and settings; the rest
(downloads, helper_bots, required_channels, payments) arrive with their phases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    # None until the user picks a language on /start
    lang: Mapped[str | None] = mapped_column(String(8))
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    referrer: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Group(Base):
    __tablename__ = "groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(String(255))
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    lang: Mapped[str | None] = mapped_column(String(8))
    auto_download: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # None = all topics allowed; otherwise list of message_thread_id (0 = General)
    allowed_topics: Mapped[list[int] | None] = mapped_column(JSON)
    # Post without thread id when the topic is gone. Off by default (section 2a).
    fallback_without_thread: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaCache(Base):
    __tablename__ = "media_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))  # video | photo | audio | document | album
    # [{kind, file_id, file_unique_id, size, chat_id, message_id}, ...] in album order
    bot_file_ids: Mapped[list[dict]] = mapped_column(JSON, default=list)
    storage_channel_id: Mapped[int] = mapped_column(BigInteger)
    storage_message_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    caption: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(BigInteger)
    hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Download(Base):
    """One processed link request: which ladder step served it and what it cost."""

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    platform: Mapped[str | None] = mapped_column(String(32), index=True)
    key: Mapped[str | None] = mapped_column(String(255))
    method: Mapped[str | None] = mapped_column(String(16))  # cache | url | relay | self
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    error_class: Mapped[str | None] = mapped_column(String(32))
    bytes_egress: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class HelperBot(Base):
    """External saver bots used by the userbot relay (brief section 3)."""

    __tablename__ = "helper_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    platforms: Mapped[str] = mapped_column(String(255), default="all", server_default="all")
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    success: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fail: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    """Key/value overrides for env settings, editable from the admin panel."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
