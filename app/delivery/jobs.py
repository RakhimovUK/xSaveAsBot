"""Payload of a link request travelling bot -> worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.bot.reply_target import ReplyTarget


@dataclass
class LinkJob:
    url: str
    target: str  # ReplyTarget JSON
    lang: str
    user_id: int | None = None
    status_message_id: int | None = None
    variant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LinkJob:
        return cls(**data)

    @classmethod
    def create(
        cls,
        url: str,
        target: ReplyTarget,
        lang: str,
        user_id: int | None,
        status_message_id: int | None,
        variant: str | None = None,
    ) -> LinkJob:
        return cls(url, target.to_json(), lang, user_id, status_message_id, variant)

    @property
    def reply_target(self) -> ReplyTarget:
        return ReplyTarget.from_json(self.target)
