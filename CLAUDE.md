# xSaveAsBot — notes for Claude Code

Telegram saver bot **@xSaveAsBot**: user sends a link, gets the media back. Full spec: `docs/BRIEF.md`
(the brief uses the earlier working name "xSaver" / @xSaverBot; the product name is xSaveAsBot).
Status and next steps: `PROGRESS.md`. Resume a session by reading these two files.

## Working agreement
- Chat with the owner (Ubaydullo) in **Uzbek**; code, comments, commits, docs in English.
- Work phase by phase (BRIEF §10). After each phase: update `PROGRESS.md`, explain how to test, stop.
- Check current library versions/APIs before using a library (yt-dlp, Telethon, aiogram… change often).
- No secrets in code. The GitHub repo is **public**: `.env`, session strings and cookies stay out of git.
- Main design goal: near-zero server egress (Railway bills per GB).

## Stack (pinned in pyproject.toml)
Python 3.12 · aiogram 3.31 (Bot API 10.3) · Telethon 1.45 (userbot; Pyrogram is unmaintained) ·
arq 0.28 + Redis · SQLAlchemy 2.1 async + Alembic + asyncpg · pydantic-settings · Fluent i18n ·
pytest + pytest-asyncio · ruff.

## Processes
| Process  | Entry                     | Role |
|----------|---------------------------|------|
| bot      | `python -m app.bot.main`  | Bot API, handlers never block; receives storage `channel_post`s |
| worker   | `python -m app.worker.main` | arq queue `xsaveasbot:worker`: `process_link` runs the delivery ladder |
| uploader | `python -m app.uploader.main` | arq queue `xsaveasbot:uploader`: `upload_files`, `relay_fetch`; the ONLY owner of userbot sessions |

Never open a Telethon session outside the uploader (one process per session).
The helper-bot relay (Phase 5) depends on third-party bots and can break at any time; it is a fallback.

## Folder map
```
app/config.py            Settings (env / .env)
app/i18n.py, locales/    Fluent .ftl per language (uz default, ru, en) — all user strings live here
app/bot/reply_target.py  ReplyTarget: chat + forum topic + reply target (BRIEF §2a)
app/bot/sender.py        THE ONLY place that sends bot messages (applies ReplyTarget)
app/bot/targets.py       ReplyTarget builders with per-group fallback setting
app/bot/middlewares/     context: DB session, user/group upsert, lang, translator `t`
app/bot/routers/         start, debug (Phase 1 test cmds + echo), storage_posts
app/delivery/            pending (waiters), cache, finalize (parts->cache->deliver), send (albums),
                         ladder (cache->url-send->relay->self), captions, egress budget, jobs
app/extractors/          url_utils (detect/keys), ytdlp, gallerydl, threads, service (chains), errors
app/relay/, uploader/relay.py  helper-bot registry + parsing; userbot conversation with helpers
app/db/                  models, session, repo; migrations in alembic/versions
app/queue/               queue names, Redis settings
app/worker/, app/uploader/  arq workers
scripts/make_session.py  one-off Telethon login -> StringSession
tests/                   unit + dispatcher flow tests (fake Bot API, SQLite, fakeredis)
```

## Conventions
- **Topic rule:** build a `ReplyTarget` from the incoming message/callback (`app/bot/targets.py`) and
  send through `Sender`. Never call `bot.send_*`, `message.answer/reply/answer_*`, `copy_message`,
  `forward` elsewhere — `tests/test_no_raw_sends.py` fails the build. `callback.answer()` is fine.
- Thread id only when `message.is_topic_message`; General topic / plain groups get none.
- Topic errors never fall back to General unless the group enabled `fallback_without_thread`.
- Storage posts carry `#key <cache-key>` in the caption (`app/bot/media_utils.py`).
- Handler deps come from dispatcher workflow data: `settings`, `sender`, `arq`, plus middleware
  `session`, `db_user`, `db_group`, `lang`, `t`.
- New user-facing string → add the key to all three `main.ftl` files (test enforces parity).
- Schema change → new Alembic revision in `alembic/versions/` (hand-written, SQLite-compatible).

## Commands
```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows path
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
alembic upgrade head
docker compose up --build              # all services locally
docker compose -f docker-compose.worker.yml up --build   # Mode A laptop side
```

## Production
Oracle Cloud Always Free VM, everything via Docker Compose; deploy with `scripts/deploy.sh`
(`.env` is copied with scp, never committed). YouTube is blocked on that IP -> relay.
