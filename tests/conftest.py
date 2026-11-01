import os
from datetime import UTC, datetime

import pytest
from aiogram.types import Message

# Minimal env so Settings() can be built in tests without a real .env
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("STORAGE_CHANNEL_DEFAULT", "-1001000000000")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def make_message(
    *,
    chat_id: int = 1,
    chat_type: str = "private",
    message_id: int = 10,
    is_forum: bool | None = None,
    thread_id: int | None = None,
    is_topic: bool | None = None,
    text: str = "hi",
    reply_to: dict | None = None,
    **extra,
) -> Message:
    chat = {"id": chat_id, "type": chat_type}
    if is_forum is not None:
        chat["is_forum"] = is_forum
    data = {
        "message_id": message_id,
        "date": datetime.now(UTC),
        "chat": chat,
        "from": {"id": 42, "is_bot": False, "first_name": "U"},
        "text": text,
        **extra,
    }
    if thread_id is not None:
        data["message_thread_id"] = thread_id
    if is_topic is not None:
        data["is_topic_message"] = is_topic
    if reply_to is not None:
        data["reply_to_message"] = reply_to
    return Message.model_validate(data)


@pytest.fixture
def msg_factory():
    return make_message
