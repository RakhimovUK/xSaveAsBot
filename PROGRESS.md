# Progress

## Deployment
Production runs 24/7 on an Oracle Cloud Always Free ARM VM (Ubuntu 24.04, Docker Compose, all five
services on one host). Server IP is intentionally not recorded in this public repo.
- Server prep: `scripts/server_setup.sh` (done 2026-11-01).
- Deploy/update: copy `.env` with `scp` (never via git), then on the server `bash scripts/deploy.sh`.
- Logs: `docker compose logs -f bot` (also `worker`, `uploader`) in `~/xSaveAsBot`.
- 2026-11-01: first deploy OK — migration 0001 applied on Postgres, bot polling as @xSaveAsBot,
  worker and uploader connected to Redis, userbot connected.

## Phase 2+ (delivery core, relay, platforms) — deployed 2026-11-02, awaiting live test
Built in one go (owner asked to finish the code, then test together):
- URL detection + canonical keys for all 15 platforms; yt-dlp 2026.10.26 (+Deno for YouTube),
  gallery-dl fallback, custom Threads parser, typed errors (`app/extractors`).
- Ladder (`app/delivery/ladder.py`): cache -> url-send -> relay -> self download; per-platform
  url-send auto-disable, daily egress budget, `downloads` table, dedup via pending waiters.
- Storage posts are tagged `#key <key> #part i/n`; albums are reassembled in Redis, cached in
  `media_cache`, delivered to every waiter in its own chat/topic; captions built fresh.
- Relay (`app/uploader/relay.py`): helper registry in DB, userbot converses with the helper bot,
  clicks quality buttons, filters junk/subscribe/error replies, validates duration, copies media
  to the storage channel, 3 fails -> 10 min cooldown, failover to the next helper.
- Bot: link handler (rate limit, ban, group auto-download + allowed topics), YouTube quality
  picker (`yv:` callbacks), admin commands `/helpers /helper_add /helper_remove /helper_on
  /helper_off /stats /health /ban /unban`.
- 97 tests; extractor probe verified on the server for Instagram, Pinterest, Facebook, SoundCloud.

### Relay helpers (live-tested 2026-11-02 with a YouTube link, 13 s end to end)
`RELAY_PARALLEL=2`: the two best helpers are asked at once, the first valid media wins, the other
is cancelled (losing a race is not a failure). Registered on the server:
- `@TinglaBot` prio 5, all platforms — works (Video/Audio buttons) — **primary**.
- `@SaveYoutubeBot` prio 10, youtube — shows quality buttons; slow/unreliable for us so far.
- `@SaveAsBot` prio 20, everything except youtube ("YouTube not supported" in its replies).
- `@Gozilla_bot` prio 30, **disabled**: demands joining channels. Join them with the userbot
  account and `/helper_on @Gozilla_bot` to use it.
Live-test fixes: thumbnail photos are never accepted as video results, audio/preview/trim
buttons are skipped, <=720p preferred, 60 s stall timeout, `/start` handshake per helper.

### Known facts / risks
- **YouTube blocks the Oracle IP** ("confirm you're not a bot"; tested 5 clients + bgutil PO
  token). YouTube therefore goes through the **helper-bot relay**; the picker only appears when
  a direct probe works (e.g. after adding cookies / WARP). Relay needs at least one helper bot.
- Vimeo and Reddit need login from this IP -> relay. TikTok probe timed out from the server once.
- Threads parser is best-effort (no public API); falls back to gallery-dl, then relay.
- Instagram image posts/stories may need session cookies (`INSTAGRAM_SESSIONS_DIR/*.txt`).

### Next steps
1. Owner adds a helper bot: `/helper_add @username all 10` then tests links (Instagram, Pinterest,
   YouTube via relay, TikTok). Check `/health` and `/stats`.
2. Not built yet (next week, after limit reset): music (Shazam, song search, lyrics), inline mode,
   group `/settings`, broadcast, mandatory subscription, ad footer, Stars premium, `rebuild_cache`,
   webhook mode, TikTok no-watermark/slideshow specifics, Spotify, cookie/session rotation admin.

## Phase 1: Skeleton — deployed, waiting for owner's live Telegram test

### Done
- Repo layout, `CLAUDE.md`, `docs/BRIEF.md`, `.env.example`, `.gitignore` (secrets excluded; repo is public).
- Config (`app/config.py`): env + `.env`, CSV lists, `STORAGE_CHANNELS` JSON, feature flags.
- DB: models `users`, `groups`, `media_cache`, `settings`; Alembic migration `0001`.
- i18n: Fluent, uz (default) / ru / en; `/start` language picker on first use, `/lang`, `/help`.
- `ReplyTarget` + `Sender` (single send gateway) with topic-error handling; AST lint test bans raw sends.
- Pending deliveries in Redis (key → waiters with their own ReplyTarget + lang).
- Storage channel `channel_post` handler: logs file_id + `#key`, delivers to waiters.
- arq worker (`ping`) and uploader (Telethon pool, `upload_test_file`, `userbot_status`).
- `scripts/make_session.py`, Dockerfiles (bot/worker/uploader), `docker-compose.yml`,
  `docker-compose.worker.yml`.
- 33 tests pass (ReplyTarget cases, Sender, i18n parity, config, pending, migration on SQLite,
  dispatcher flow: echo in General + 3 topics, picker in topic, storage post → topic delivery).

### Verified on the server
- Docker images build on ARM, Postgres migration, bot polling, worker/uploader start, userbot login.

### Not verified yet (needs the owner in Telegram)
- `/ping` arq round-trip, `/testupload` storage round-trip, topic routing in a real forum group.

### Test commands for the owner (Phase 1)
1. Fill `.env` from `.env.example` (BOT_TOKEN, ADMIN_IDS, TG_API_ID/HASH, STORAGE_CHANNEL_DEFAULT).
2. `python scripts/make_session.py` → put the string into `USERBOT_SESSIONS`.
3. `docker compose up --build` (or run the three processes with Railway Postgres/Redis URLs).
4. In Telegram:
   - `/start` in private → pick each language, `/lang` to switch; check uz/ru/en texts.
   - `/userbot` → shows the userbot online.
   - `/ping` → "Worker replied: pong:…".
   - `/testupload` → a blue square is posted to the storage channel by the userbot and comes
     back to you with its file_id (bot log line `storage post … file_id=…`).
   - Forum group (bot admin, privacy mode off): write text in General and in 3 topics → each echo
     lands in the same topic as a reply. `/where` shows chat/thread ids. `/testupload` inside a
     topic → the photo comes back into that topic.

### Known issues / notes
- Webhook mode is a stub (Phase 9). `FEATURE_ECHO=true` is a Phase 1 test aid; turn it off later.
- Bot API 10.3 also allows topics in private chats; the `is_topic_message` rule covers that too.

## Next: Phase 2 — Delivery core + YouTube
Delivery ladder (cache → self-upload), media_cache writes from storage posts, `downloads` table,
egress budget, yt-dlp YouTube extractor (check current version + anti-bot guidance), quality picker
with sizes, MP3 with tags, progress edits, friendly errors.
