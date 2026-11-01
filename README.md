# xSaver

Telegram bot that downloads media from links (Instagram, YouTube, TikTok, Threads, Pinterest and more)
and delivers it with near-zero server egress via private storage channels.

- Spec: [docs/BRIEF.md](docs/BRIEF.md)
- Status: [PROGRESS.md](PROGRESS.md)
- Developer notes: [CLAUDE.md](CLAUDE.md)

## Quick start (local)
```bash
cp .env.example .env    # fill in tokens and channel ids
python scripts/make_session.py   # userbot StringSession -> USERBOT_SESSIONS
docker compose up --build
```

Bot setup in @BotFather: turn **privacy mode off** (Group Privacy → Disable) so the bot sees links in
groups, or make it a group admin. The bot and the userbot must both be admins of every storage channel.
