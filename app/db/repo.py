"""Small data-access helpers used by handlers."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, User


async def touch_user(session: AsyncSession, tg_id: int, username: str | None) -> User:
    """Get or create the user and bump last_seen_at."""
    user = await session.get(User, tg_id)
    if user is None:
        user = User(tg_id=tg_id, username=username)
        session.add(user)
    else:
        user.username = username
        user.last_seen_at = func.now()
    await session.flush()
    return user


async def set_user_lang(session: AsyncSession, tg_id: int, lang: str) -> None:
    user = await session.get(User, tg_id)
    if user is not None:
        user.lang = lang


async def touch_group(
    session: AsyncSession, chat_id: int, title: str | None, is_forum: bool
) -> Group:
    group = await session.get(Group, chat_id)
    if group is None:
        group = Group(chat_id=chat_id, title=title, is_forum=is_forum)
        session.add(group)
    else:
        group.title = title
        group.is_forum = is_forum
    await session.flush()
    return group
