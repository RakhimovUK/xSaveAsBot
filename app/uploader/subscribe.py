"""Join the channels a helper bot demands (mandatory subscription) with the userbot.

Authorised by the owner as a standing rule: when a helper bot asks for a subscription,
join and confirm. Only channels/groups offered as URL buttons of a helper's own prompt
are joined (never bots/users), a handful per prompt, and a prompt is handled once per
10 minutes per helper to avoid loops."""

from __future__ import annotations

import logging
import re
from typing import Any

from redis.asyncio import Redis
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel

log = logging.getLogger(__name__)

MAX_JOINS = 5
COOLDOWN_S = 600
CHECK_MARKERS = ("провер", "check", "tekshir", "подписал", "i subscribed", "готово", "done")
LINK_RE = re.compile(r"(?:https?://)?(?:t|telegram)\.me/(?:joinchat/|\+)?([A-Za-z0-9_-]+)", re.I)


def parse_channel_link(url: str) -> tuple[str, str] | None:
    """('invite', hash) | ('name', username) for a t.me link; None otherwise."""
    m = LINK_RE.match(url.strip())
    if not m:
        return None
    path = url.split("t.me/", 1)[-1].split("telegram.me/", 1)[-1]
    if path.startswith(("+", "joinchat/")):
        return "invite", m.group(1)
    name = m.group(1)
    if name.lower().endswith("bot") or len(name) < 4:
        return None  # bots / tiny names are not channels
    return "name", name


def check_button(msg: Any) -> tuple[int, int] | None:
    """The callback button that re-checks the subscription, if any."""
    for i, row in enumerate(msg.buttons or []):
        for j, button in enumerate(row):
            if getattr(button, "url", None):
                continue
            if any(mark in (button.text or "").lower() for mark in CHECK_MARKERS):
                return i, j
    return None


async def auto_subscribe(client: TelegramClient, redis: Redis, helper: str, msg: Any) -> bool:
    """Join the offered channels and press 'check'. True when something was done."""
    flag = f"xsaveasbot:relay:subscribe:{helper}"
    if not await redis.set(flag, "1", nx=True, ex=COOLDOWN_S):
        return False
    joined = 0
    for row in msg.buttons or []:
        for button in row:
            url = getattr(button, "url", None)
            target = parse_channel_link(url) if url else None
            if target is None or joined >= MAX_JOINS:
                continue
            kind, ref = target
            try:
                if kind == "invite":
                    await client(ImportChatInviteRequest(ref))
                else:
                    entity = await client.get_entity(ref)
                    if not isinstance(entity, Channel):
                        continue
                    await client(JoinChannelRequest(entity))
                joined += 1
                log.info("subscribe: @%s demanded %s -> joined", helper, ref)
            except Exception as exc:
                text = str(exc)
                if "already" in text.lower() or "USER_ALREADY_PARTICIPANT" in text:
                    joined += 1
                else:
                    log.warning("subscribe: could not join %s for @%s: %s", ref, helper, exc)
    pick = check_button(msg)
    if pick:
        try:
            await msg.click(*pick)
            log.info("subscribe: pressed the check button for @%s", helper)
        except Exception as exc:
            log.warning("subscribe: check click failed for @%s: %s", helper, exc)
    return joined > 0 or pick is not None
