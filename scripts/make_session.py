"""Log in with the userbot account once and print a Telethon StringSession.

Run on your own machine:  python scripts/make_session.py
Put the printed string into USERBOT_SESSIONS. Treat it like a password: it gives
full access to the account. Never commit it or paste it into chats.
"""

import asyncio
import getpass
import os

from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

MAX_ATTEMPTS = 3


async def ask(prompt: str, *, secret: bool = False) -> str:
    reader = getpass.getpass if secret else input
    return (await asyncio.to_thread(reader, prompt)).strip()


async def sign_in_with_password(client: TelegramClient) -> None:
    # Each sign_in(password=...) fetches fresh SRP parameters, so a typo doesn't
    # poison the next attempt (Telethon's start() can fail with SrpIdInvalidError).
    for _ in range(MAX_ATTEMPTS):
        password = await ask("2FA password (hidden while typing): ", secret=True)
        try:
            await client.sign_in(password=password)
            return
        except PasswordHashInvalidError:
            print("Wrong 2FA password, try again.")
    raise SystemExit("Too many wrong passwords. Run the script again later.")


async def login(api_id: int, api_hash: str) -> None:
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        phone = await ask("Phone in international format (e.g. +998901234567): ")
        await client.send_code_request(phone)
        for _ in range(MAX_ATTEMPTS):
            code = await ask("Login code from Telegram: ")
            try:
                await client.sign_in(phone=phone, code=code)
                break
            except SessionPasswordNeededError:
                await sign_in_with_password(client)
                break
            except PhoneCodeInvalidError:
                print("Wrong code, try again.")
            except PhoneCodeExpiredError:
                raise SystemExit("Code expired. Run the script again.") from None
        else:
            raise SystemExit("Too many wrong codes. Run the script again later.")

        me = await client.get_me()
        print(f"\nLogged in as {me.first_name} (@{me.username}, id={me.id})")
        print("\nUSERBOT_SESSIONS value (keep it secret, paste only into .env):\n")
        print(client.session.save())
    finally:
        await client.disconnect()


if __name__ == "__main__":
    api_id = int(os.environ.get("TG_API_ID") or input("TG_API_ID: ").strip())
    api_hash = os.environ.get("TG_API_HASH") or getpass.getpass("TG_API_HASH (hidden): ").strip()
    asyncio.run(login(api_id, api_hash))
