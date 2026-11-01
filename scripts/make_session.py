"""Log in with the userbot account once and print a Telethon StringSession.

Run on your own machine:  python scripts/make_session.py
Put the printed string into USERBOT_SESSIONS. Treat it like a password: it gives
full access to the account. Never commit it or paste it into chats.
"""

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def login(api_id: int, api_hash: str) -> None:
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()  # prompts for phone, code and 2FA password
    me = await client.get_me()
    print(f"\nLogged in as {me.first_name} (@{me.username}, id={me.id})")
    print("\nUSERBOT_SESSIONS value (keep it secret):\n")
    print(client.session.save())
    await client.disconnect()


if __name__ == "__main__":
    api_id = int(os.environ.get("TG_API_ID") or input("TG_API_ID: ").strip())
    api_hash = os.environ.get("TG_API_HASH") or input("TG_API_HASH: ").strip()
    asyncio.run(login(api_id, api_hash))
