"""Application settings, loaded from environment / .env.

Comma-separated values (ADMIN_IDS, USERBOT_SESSIONS, PLATFORMS_ENABLED) are parsed
manually; STORAGE_CHANNELS is JSON.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SUPPORTED_LANGS = ("uz", "ru", "en")


def _split_csv(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def normalize_db_url(url: str) -> str:
    """Railway/Heroku give postgres:// or postgresql://; SQLAlchemy async needs asyncpg."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram bot
    bot_token: str
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    default_lang: Literal["uz", "ru", "en"] = "uz"
    mode: Literal["polling", "webhook"] = "polling"
    webhook_url: str = ""

    # Userbot
    tg_api_id: int = 0
    tg_api_hash: str = ""
    userbot_sessions: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Storage channels
    storage_channels: dict[str, int] = Field(default_factory=dict)
    storage_channel_default: int
    inbox_channel: int | None = None

    # Infra
    database_url: str = "postgresql+asyncpg://xsaveasbot:xsaveasbot@localhost:5432/xsaveasbot"
    redis_url: str = "redis://localhost:6379/0"

    # Limits
    max_duration_min: int = 180
    max_self_upload_mb: int = 1900
    relay_threshold_mb: int = 50
    relay_timeout_s: int = 120
    relay_parallel: int = 2  # helpers raced at once; first valid media wins
    egress_daily_budget_gb: float = 5.0
    user_rate_limit: int = 10
    worker_concurrency: int = 4
    uploader_concurrency: int = 2

    # Feature flags
    platforms_enabled: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "youtube",
            "instagram",
            "tiktok",
            "threads",
            "pinterest",
            "facebook",
            "twitter",
            "snapchat",
            "likee",
            "vk",
            "soundcloud",
            "reddit",
            "twitch",
            "vimeo",
        ]
    )
    feature_lyrics: bool = True
    feature_relay: bool = True
    relay_tier2: bool = True
    feature_url_send: bool = True
    feature_mandatory_sub: bool = False
    feature_ads: bool = False
    feature_premium: bool = False
    feature_echo: bool = True

    # Shared between worker and uploader (same volume / same machine)
    jobs_dir: str = "/tmp/xsaveasbot-jobs"
    url_send_max_mb: int = 20
    url_send_photo_max_mb: int = 5

    # Anti-blocking
    instagram_sessions_dir: str = "./secrets/instagram"
    yt_cookies_path: str = ""
    proxy_url_instagram: str = ""
    proxy_url_youtube: str = ""

    # Monitoring
    sentry_dsn: str = ""
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        return [int(x) for x in _split_csv(v)]

    @field_validator("userbot_sessions", mode="before")
    @classmethod
    def _parse_sessions(cls, v: object) -> list[str]:
        return _split_csv(v)

    @field_validator("platforms_enabled", mode="before")
    @classmethod
    def _parse_platforms(cls, v: object) -> list[str]:
        return [p.lower() for p in _split_csv(v)]

    @field_validator("database_url")
    @classmethod
    def _db_url(cls, v: str) -> str:
        return normalize_db_url(v)

    @field_validator("inbox_channel", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    def storage_channel_for(self, platform: str) -> int:
        """Storage channel for a platform, falling back to the default channel."""
        return self.storage_channels.get(platform, self.storage_channel_default)

    @property
    def all_storage_channel_ids(self) -> set[int]:
        return {self.storage_channel_default, *self.storage_channels.values()}

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
