"""arq queue names and Redis settings shared by bot, worker and uploader."""

from arq.connections import RedisSettings

# Download/probe jobs (Phase 2+). Runs on the laptop in Mode A.
WORKER_QUEUE = "xsaveasbot:worker"
# Jobs that need the userbot session. Only the uploader process consumes this queue,
# so a Telethon session is never opened by two processes at once.
UPLOADER_QUEUE = "xsaveasbot:uploader"


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)
