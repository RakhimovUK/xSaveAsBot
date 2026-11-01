"""Userbot pool. Only the uploader process may create it (one process per session)."""

from __future__ import annotations

import itertools
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

log = logging.getLogger(__name__)


class UserbotPool:
    def __init__(self, sessions: list[str], api_id: int, api_hash: str) -> None:
        if not sessions:
            raise RuntimeError("USERBOT_SESSIONS is empty; run scripts/make_session.py")
        if not api_id or not api_hash:
            raise RuntimeError("TG_API_ID / TG_API_HASH are required for the userbot")
        self.clients = [TelegramClient(StringSession(s), api_id, api_hash) for s in sessions]
        self._cycle = itertools.cycle(self.clients)
        self.names: list[str] = []

    async def start(self) -> None:
        for client in self.clients:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("A userbot session is not authorized; regenerate it")
            me = await client.get_me()
            # A fresh StringSession has no entity cache; loading dialogs lets us
            # address storage channels by their -100… id.
            await client.get_dialogs()
            name = f"@{me.username}" if me.username else str(me.id)
            self.names.append(name)
            log.info("Userbot %s connected", name)

    async def stop(self) -> None:
        for client in self.clients:
            await client.disconnect()

    def get(self) -> TelegramClient:
        return next(self._cycle)
