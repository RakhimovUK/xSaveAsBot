# xSaver Bot — Build Brief for Claude Code (v2)

> Paste this whole file as your first message in Claude Code (or save it in the repo as `docs/BRIEF.md` and tell Claude Code to read it).

---

## 0. How we work (read first)

- I am Ubaydullo. **Talk to me in Uzbek** in chat; write code, comments, commit messages and docs in English.
- I'm on Claude Pro, so usage resets in 5-hour windows. Work **phase by phase** (section 10). At the end of every phase:
  1. Update `PROGRESS.md` (what is done, what is next, known issues, exact commands to run).
  2. Stop and tell me how to test that phase locally. Don't start the next phase until I confirm.
- Create a `CLAUDE.md` at the repo root on day one with: project summary, stack, folder map, run/test commands, conventions. Keep it current so that a fresh session can resume with only `CLAUDE.md` + `PROGRESS.md`.
- Before using any library, **check its current version and current API** (pip index / docs / GitHub). Downloader and MTProto libraries change often; don't rely on memory. That applies especially to yt-dlp, instaloader, gallery-dl, shazamio, Telethon/Pyrogram and aiogram.
- Prefer small, working increments over big rewrites. Run the code and tests yourself before saying something works.
- Don't hard-code any secrets. Everything goes through `.env` / Railway variables, and there's a `.env.example`.
- **Main design goal: keep server egress (outgoing traffic) as close to zero as possible.** Railway bills egress per GB. Every design choice below follows from this.

---

## 1. Product

**xSaver** is a Telegram bot. The user sends a link and gets the media back. It's for my own use first and will go public later, so build public-ready plumbing now, behind feature flags.

Supported platforms in v1 are split into two tiers.

### Tier 1: Core platforms (5)
Full feature set, the whole fallback chain (yt-dlp + alternative extractors + cookies/session rotation), the delivery ladder including helper-bot relay, priority in the queue, full test coverage, and alerts to the admin when they break. These must always work.

- **Instagram**: reels, single photo/video posts, carousels (sent as a media group, up to 10 items), stories and highlights (need a logged-in session), plus the caption.
- **YouTube**: videos with a quality picker (360p/720p/1080p, plus higher when allowed by the size limit), each button showing the estimated file size. Shorts are supported. Audio comes as MP3 with title, artist and embedded thumbnail.
- **TikTok** (the most-requested platform after Instagram): videos **without watermark** when available, photo slideshows (sent as an album), audio as MP3. Includes `vm.tiktok.com` / `vt.tiktok.com` short links.
- **Threads**: post videos and images (single and multiple).
- **Pinterest**: pin images and videos, including `pin.it` short links.

### Tier 2: Extra platforms (10)
Best effort: yt-dlp only (no custom fallbacks unless trivial), the basic delivery ladder (cache → URL-send → self), one smoke test per platform, and each can be switched off via `PLATFORMS_ENABLED` without affecting anything else. A Tier 2 failure gives the user a short "this platform is temporarily unavailable" message and an admin log entry, never an urgent alert. Helper-bot relay for Tier 2 is behind a separate flag `RELAY_TIER2=false`.

- **Facebook**: videos, Reels, `fb.watch` links (public content).
- **X / Twitter**: videos, GIFs (sent as animation), images; both `x.com` and `twitter.com`.
- **Snapchat**: Spotlight and public story videos.
- **Likee**: videos.
- **VK**: videos and clips (public).
- **SoundCloud**: tracks as MP3 with tags and artwork.
- **Spotify**: track links → read title/artist from the link's metadata (oEmbed / page meta, no Spotify account), then find the track on YouTube and send the MP3. Album/playlist links: show the track list as buttons.
- **Reddit, Twitch clips, Vimeo**: videos (with audio merged for Reddit).

The extractor registry holds each platform's tier (`core` / `extra`). Stats, health-check and the admin panel show the two tiers separately. For every platform, use yt-dlp first where it has an extractor (verify its current state). Add fallbacks (gallery-dl or a small custom extractor) only where yt-dlp fails in testing. All platforms share the same extractor interface, so adding one is a single new module plus tests.

Extra v1 features:
1. **Music recognition (Shazam-like).** Every downloaded video or reel gets a 🎵 "Find the song" button. Pressing it extracts a ~15–20 s audio slice with ffmpeg, recognizes it with `shazamio`, shows the artist and title, and offers "⬇️ Download full MP3", which finds the track on YouTube and sends it as MP3. The same flow works when the user sends a voice message, audio, video or video note directly.
2. **Song search.** A plain text message that isn't a link means a song search. Show the top 5–10 YouTube results as inline buttons; tapping one sends the MP3.
2b. **Lyrics.**
   - Source: **LRCLIB** (free public API, no key; check current endpoints). It returns plain lyrics and **synced (LRC)** lyrics. Keep the source behind a `LyricsProvider` interface so another provider can be added later.
   - Entry points: a "📝 Lyrics" button next to every Shazam result and every MP3 we send (we know artist/title/duration there, so use them for an exact match); the `/lyrics <song name>` command; and the "Lyrics" button in song-search results.
   - Output: lyrics as text (split across messages if over 4096 chars, or one message + "show full" pagination buttons), plus a "⬇️ .lrc file" button that sends the synced lyrics as an `Artist - Title.lrc` document (for people who edit videos/audio). If no synced version exists, hide that button.
   - Cache lyrics lookups in Postgres/Redis by normalized artist+title.
   - Respects forum topics like everything else.
   - Flag: `FEATURE_LYRICS=true`.
3. **Inline mode.** Three inline query types:
   - `@xSaverBot <link>`: media (details below).
   - `@xSaverBot lyrics <song>` (also `@xSaverBot l <song>` / `текст <song>` / `matn <song>`): article results (title, artist, first lines as the description). Choosing one sends the lyrics text (trimmed to the limit, with a "Full lyrics in bot" deep-link button when trimmed).
   - `@xSaverBot <song name>` (non-link text): music search results. Cached tracks come back as audio results; uncached ones use the placeholder → `editMessageMedia` flow.
   Media links work like this: `@xSaverBot <link>` in any chat. If the media is cached, return its `file_id` result right away. If not, return a placeholder result that has a reply_markup (so we get an `inline_message_id`), process it in the background on `chosen_inline_result`, then `editMessageMedia` it. Inline feedback must be enabled in BotFather; document this.
4. **Groups, including forum topics (TOP PRIORITY: this is how I use saver bots every day).** When a supported link appears in a group, the bot replies with the media. In forum supergroups (groups with topics), **every reply must land in the exact same topic the link was sent in**. See section 2a; this is a hard requirement, not a nice-to-have. Document that privacy mode must be off (or the bot must be admin). Group admins get a `/settings` command to toggle auto-download.
5. **Extract audio from video.** A user sends any video and taps "🎧 Extract MP3".
6. **Languages**: Uzbek (default, Latin script), Russian, English. Ask on `/start` and allow changing via `/lang`. Use a proper i18n setup. Keep all strings in locale files.

Admin and monetization plumbing (built in v1, **disabled by default** with flags):
- **Admin panel** (Telegram commands/keyboards, admin IDs from env): stats (users, DAU, downloads per platform, delivery method breakdown, cache hit rate, relay success rate, errors), **broadcast** (text/photo/video with buttons, via a throttled queue that handles blocked users and FloodWait, with a progress report), user lookup, ban/unban.
- **Mandatory subscription**: admin can add or remove channels; when the flag is on, a user must join them before downloading.
- **Ad footer**: admin-configurable text appended to captions; flag-controlled.
- **Premium**: no ads, higher limits, priority queue. Payment via **Telegram Stars** (`XTR` invoices). Keep it flag-off but fully coded and tested.

Explicitly **out of scope**: pulling content from Telegram channels that have "Restrict saving content" enabled. Don't build that.

---

## 2a. Forum topics: replies must stay in the same topic (hard requirement)

I keep saver bots in a forum supergroup with many topics (e.g. "General", "Anubis", "Dust", "Audio for edit"…). If I drop a link in topic X, the answer must appear in topic X: not in General, not in another topic. Bots that got this wrong are why I stopped using several of them. Build it into the core from Phase 1, not as a later add-on.

Implementation rules:
- Introduce a single **`ReplyTarget`** object: `chat_id`, `message_thread_id` (nullable), `reply_to_message_id`, plus `inline_message_id` for inline mode. Build it once from the incoming message. **Every** outgoing call goes through a helper that applies it: text, ⏳ status messages, `sendVideo` / `sendPhoto` / `sendAudio` / `sendDocument`, `sendMediaGroup`, `copyMessage`, chat actions (`sendChatAction` also takes `message_thread_id`), error messages, mandatory-subscription prompts. No raw `bot.send_*` calls anywhere else. Add a lint/test check that enforces this.
- Take `message_thread_id` from the message **only when `message.is_topic_message` is true**. The **General** topic has no thread id. Passing a thread id there (or a wrong one) gives "message thread not found", so omit it. Non-forum groups and private chats: no thread id.
- **Callback flows** (YouTube quality picker, 🎵 Find the song, 🎧 MP3, search results): derive the target from `callback.message` (its `chat.id`, `message_thread_id` and `is_topic_message`), so the follow-up stays in the same topic.
- **Background delivery**: the queue job and the Redis "pending deliveries" entry store the full `ReplyTarget`. When the storage-channel post arrives later, delivery goes back to the right chat **and topic**. If several users request the same key from different topics, each one gets it in their own topic.
- Reply to the user's original message (`reply_parameters` with `allow_sending_without_reply=True`, so it still works if the message was deleted).
- Errors: if the topic was closed or deleted, or the bot lacks rights in it, log it and fall back to a reply without a thread id **only if** the admin enabled that in group settings. Never silently post to General by default.
- Per-group settings can also restrict the bot to selected topics (`/settings` → "Only respond in these topics"). Default: all topics.
- Tests: unit tests for `ReplyTarget` construction (private chat, normal group, forum General, forum topic, callback in a topic), plus a manual checklist: link in General, link in 3 different topics at the same time, YouTube quality picker in a topic, Shazam in a topic, carousel in a topic, a cached item in a topic.

## 2. Core idea: userbot + private storage channels + zero-egress delivery

We do **not** use a Local Bot API server. Instead:

- **Bot** (aiogram, Bot API): talks to users.
- **Userbot** (Telethon or Pyrogram, pick the better-maintained one after checking): a real, secondary Telegram account I provide. It can upload files up to 2 GB (4 GB with Premium), download user-sent files of any size, and talk to other bots.
- **Private storage channels** (I own them; both the bot and the userbot are admins in all of them). Configure them with a mapping `STORAGE_CHANNELS` (JSON: `{"instagram": -100…, "youtube": -100…, "tiktok": -100…, "music": -100…}`) plus a required `STORAGE_CHANNEL_DEFAULT` for any platform without its own channel. Platforms can be split out into their own channels later without code changes.
  - Every piece of media we ever deliver ends up in the matching storage channel.
  - When a new post appears there, the bot receives a `channel_post` update and gets **its own `file_id`** from it. That file_id goes into the cache.
  - Delivery to users is always by `file_id` or `copyMessage` from the storage channel, so **no bytes leave our server** at delivery time.
  - If the bot is ever banned, a new bot made admin of the storage channels can rebuild the cache from `(channel_id, message_id)` records. Write a `rebuild_cache` admin command for this.
  - Each storage post's caption holds a machine-readable tag (e.g. `#key yt:dQw4w9WgXcQ:720p`) so the cache can be rebuilt from the channel alone.

### Delivery ladder (try in order; record which step succeeded in `downloads.method`)

1. **Cache hit**: the `media_cache` key exists, so send by `file_id` (or `copyMessage` from storage if the file_id fails). Zero egress.
2. **Direct URL send** (`url`): if the extractor gives a direct CDN URL and the file is small enough (Bot API URL limits: ~5 MB photos, ~20 MB other files; check the current docs), call `sendPhoto` / `sendVideo` / `sendDocument` **with the URL** into the storage channel. Telegram's servers fetch it themselves, so our server sends zero bytes. Then cache and deliver. Try it for every platform except YouTube and record per-platform success rates (CDNs differ: some block Telegram's fetcher, some URLs expire fast). Auto-disable URL-send for a platform whose success rate drops below a threshold. **It doesn't work for YouTube**: googlevideo URLs are bound to the requesting IP, so skip this step for YouTube. If Telegram rejects the URL, fall through.
3. **Helper-bot relay** (`relay`), for big files and as a fallback (section 3). Zero egress.
4. **Self download + userbot upload** (`self`): the worker downloads with yt-dlp etc., the userbot uploads to the storage channel, and the bot gets the channel_post and delivers. This is the only step that costs egress. Guard it with `MAX_SELF_UPLOAD_MB` and a per-day egress budget (`EGRESS_DAILY_BUDGET_GB`, tracked in Redis). Over budget → tell the user to try later.

`RELAY_THRESHOLD_MB` decides when to go to relay *before* self-upload (e.g. files above 50 MB go to relay first). All thresholds come from env and can be changed via admin settings.

---

## 3. Helper-bot relay (automated)

For large files, or when our own extraction fails, we ask an **external public saver bot** to fetch the media, then pass its result to the user. Everything happens inside Telegram, so it costs us zero egress.

Flow:
1. The worker pushes a relay job: `{key, url, platform, variant}`.
2. The userbot sends the URL to a helper bot in a private chat. (Normal bots don't see messages from other bots, so the userbot is the bridge. Check this against current Telegram docs.)
3. The userbot waits for the reply (media message or album). It handles the helper's quirks: quality-picker buttons (click the configured choice), "processing…" messages, mandatory-subscription prompts (log an alert for the admin; don't auto-join random channels unless the channel is on an allowlist).
4. The userbot **copies** (not forwards, so there's no "forwarded from" header) the media to the matching storage channel, with **our own caption** (the `#key` tag + the original post caption from our own probe, if we have it).
5. The bot gets the channel_post, caches the file_id, and delivers to the user.

Requirements:
- A **helper registry** in the DB: username, supported platforms, priority, enabled, success/fail counters, avg latency, last error, cooldown_until. Admin commands to add, remove, enable and disable helpers and view stats.
- **Correlation**: helpers reply asynchronously and without request IDs. Keep **one in-flight request per helper chat** (Redis lock). Match the reply to the request by order and time window, and validate it (media type and duration/size close to what our probe expected, when known). Use several helpers and/or several userbot accounts for parallelism.
- **Timeouts and failover**: if there's no media reply within `RELAY_TIMEOUT_S`, mark a failure, put the helper on cooldown after N consecutive fails, and try the next helper. If all fail, go to delivery step 4 (or a friendly error).
- **Detection of junk replies**: errors, ads and "subscribe to …" messages should not be delivered to users.
- Rate-limit the userbot's outgoing messages to stay well under Telegram's limits. Handle FloodWait.
- Note in `CLAUDE.md` that the relay depends on third parties and can break at any time. It's a fallback, not the core.

---

## 4. Tech stack

- Python 3.12+, **aiogram 3.x** for the bot
- **Telethon or Pyrogram** for the userbot (StringSession from env; a local `scripts/make_session.py` I run once on my laptop to log in and print the session string)
- **yt-dlp** as the main extractor (YouTube, Instagram, Pinterest, and Threads if supported), plus a startup log of its version
- **instaloader** and/or **gallery-dl** as fallbacks for Instagram and Pinterest
- **Threads**: check current yt-dlp/gallery-dl support first. If neither works reliably, write a small isolated custom extractor (parse the embedded JSON for media URLs).
- **ffmpeg**, **shazamio**, **LRCLIB** (lyrics over HTTP via httpx)
- **Redis** + **arq** for queues, locks, rate limits, the egress budget and relay coordination
- **PostgreSQL** with SQLAlchemy 2.x async + **Alembic**
- Docker + `docker-compose.yml` for local dev
- pytest + pytest-asyncio; ruff

---

## 5. Architecture

```
User ⇄ Bot (aiogram) ──enqueue──► Redis (arq) ──► Worker: probe → choose ladder step
                                                          │
                     ┌──────────────── url-send ──────────┤ (Bot API sends CDN URL to storage channel)
                     │                                    │
                     │      Uploader service (holds the userbot session)
                     │        ├─ self-upload file → storage channel
                     │        └─ relay: talk to helper bots → copy result → storage channel
                     ▼
            Storage channels ──channel_post──► Bot: save file_id in cache → deliver to waiting user(s)
                                     PostgreSQL: users, cache, downloads, helpers, settings, payments
```

Rules:
- **Handlers never block.** They validate, check the cache, enqueue, and reply "⏳ …" (then edit with progress or the result).
- **One process per userbot session.** A Telethon/Pyrogram session must never be used by two processes at once. Run a dedicated **uploader** service that owns the userbot client(s) and takes commands from Redis (upload file / relay URL / download user file). Workers never open the session themselves.
- **Pending deliveries**: when a job is submitted, store `key → [waiting chat_ids / inline_message_ids]` in Redis. When the channel_post for that key arrives, deliver to everyone waiting. This also gives in-flight dedup for free.
- **Cache key** = `platform + canonical media id + variant` (`yt:<id>:720p`, `yt:<id>:mp3`, `ig:<shortcode>:<index>`, `pin:<id>`, `th:<id>:<index>`, `tt:<id>`, `tt:<id>:mp3`, `fb:<id>`, `x:<id>:<index>`, `sc:<id>`, `sp:<track_id>` → points to the YouTube MP3 key, etc.). Canonicalize URLs (strip tracking params, resolve `youtu.be`, `pin.it`, `instagr.am`, `vm.tiktok.com`, `fb.watch`, `t.co`, `spotify.link`, etc.).
- **Extractor interface**: `can_handle(url) / probe(url) -> MediaInfo (incl. direct URLs, sizes, duration) / download(url, variant, workdir) -> list[File]`. One module per platform, each with an ordered fallback chain.
- **User-sent files** (Shazam, extract MP3): the bot asks the uploader's userbot to download the file from the user's message. Easiest path: the bot copies the user's message into a private "inbox" channel that the userbot reads, and the userbot downloads it there. No Bot API 20 MB download limit applies.
- **Limits** (env): max duration, per-user rate limit, per-user concurrent jobs, worker concurrency, the thresholds from section 2. Premium users get higher values and a priority queue.
- **Temp files**: one temp dir per job, cleaned up in `finally`, plus a periodic sweeper.
- **Friendly errors** in the user's language: private account, deleted post, too large, age-restricted, unsupported link, rate limited, egress budget reached, try later.

### Anti-blocking
- **Instagram**: multiple session/cookie files (burner accounts) with rotation and cooldown on failures. Admin commands to upload cookies and list session health.
- **YouTube**: `cookies.txt` support, plus whatever yt-dlp **currently** recommends against "Sign in to confirm you're not a bot" (research it, e.g. PO-token provider plugins).
- Optional per-platform `PROXY_URL_*`.
- A **health-check** admin command: tests each platform's extractor, the URL-send step, each helper bot, and the userbot connection, then reports the results.

### Deployment modes (both must work)
- **Mode A, laptop worker (default for personal use):** bot, Postgres and Redis run on Railway; the worker and uploader run on my laptop (residential IP, so fewer blocks and no egress bill for self-downloads). They connect to Railway Redis/Postgres via their public TCP proxy URLs. Provide `docker-compose.worker.yml` for the laptop.
- **Mode B, all on Railway:** every service on Railway, using private networking. Provide Dockerfiles, `railway.json`, and a step-by-step `DEPLOY.md` (variables per service; how to create storage channels and add the bot + userbot as admins; how to generate the session string).
- Long polling by default; webhook mode is a config switch.

---

## 6. Data model (starting point)

- `users`: tg_id, username, lang, is_premium, premium_until, is_banned, created_at, last_seen_at, referrer
- `media_cache`: key (unique), platform, kind, bot_file_ids (json), storage_channel_id, storage_message_ids (json), caption, size, hits, created_at
- `downloads`: id, user_id, platform, key, method (`cache|url|relay|self`), status, error_class, bytes_egress, duration_ms, created_at
- `helper_bots`: username, platforms, priority, enabled, success, fail, avg_latency_ms, last_error, cooldown_until
- `groups`, `required_channels`, `settings` (key/value, overrides env), `payments`

---

## 7. UX details

- `/start`: language picker (first time), then a short welcome listing platforms and features.
- `/help`, `/lang`, `/premium` (flag), `/admin` (admins only)
- Link → "⏳ Analyzing…" → for YouTube, a quality keyboard with sizes plus 🎧 MP3 → progress edits → result. Result buttons: 🎵 Find the song, 🎧 MP3 (for video).
- The user-facing caption is built fresh by the bot when delivering: original caption (trimmed) + source link + bot username (+ ad footer if enabled). **Don't** pass through helper bots' captions or ads.
- Carousel: media group in chunks of 10, caption on the first item.
- Audio: proper `title` / `performer` / thumbnail, filename `Artist - Title.mp3`.

---

## 8. Config (`.env.example`)

At least: `BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH`, `USERBOT_SESSIONS` (comma-separated string sessions), `STORAGE_CHANNELS` (JSON), `STORAGE_CHANNEL_DEFAULT`, `INBOX_CHANNEL`, `FEATURE_LYRICS=true`, `PLATFORMS_ENABLED` (comma list, so a broken platform can be switched off quickly), `DATABASE_URL`, `REDIS_URL`, `ADMIN_IDS`, `DEFAULT_LANG=uz`, `MAX_DURATION_MIN`, `MAX_SELF_UPLOAD_MB`, `RELAY_THRESHOLD_MB`, `RELAY_TIMEOUT_S`, `EGRESS_DAILY_BUDGET_GB`, `USER_RATE_LIMIT`, `WORKER_CONCURRENCY`, `FEATURE_RELAY=true`, `FEATURE_URL_SEND=true`, `FEATURE_MANDATORY_SUB=false`, `FEATURE_ADS=false`, `FEATURE_PREMIUM=false`, `INSTAGRAM_SESSIONS_DIR`, `YT_COOKIES_PATH`, `PROXY_URL_INSTAGRAM`, `PROXY_URL_YOUTUBE`, `SENTRY_DSN`, `MODE=polling|webhook`, `WEBHOOK_URL`.

---

## 9. Repo layout (suggested)

```
xsaver/
  CLAUDE.md  PROGRESS.md  DEPLOY.md  README.md  .env.example
  docker-compose.yml  docker-compose.worker.yml  Dockerfile.bot  Dockerfile.worker  Dockerfile.uploader
  alembic/  scripts/make_session.py
  app/
    config.py  db/  cache/  queue/
    bot/ (main.py, routers/: start, links, inline, groups, music, search, admin, payments, storage_posts; middlewares/: i18n, ban, subscription, throttle)
    uploader/ (main.py, userbot pool, upload.py, relay/: registry.py, session.py, parsers.py, inbox.py)
    extractors/ (base.py, registry.py, url_utils.py, youtube.py, instagram.py, threads.py, pinterest.py, tiktok.py, facebook.py, twitter.py, snapchat.py, likee.py, vk.py, soundcloud.py, spotify.py, reddit.py, twitch.py, vimeo.py)
    delivery/ (ladder.py, url_send.py, pending.py, egress_budget.py)
    media/  music/ (shazam.py, yt_search.py)  lyrics/ (provider.py, lrclib.py, render.py)
    services/ (broadcast, stats, health, rebuild_cache)
    locales/ uz/ ru/ en/
  tests/
```

---

## 10. Phases (stop after each one for my confirmation)

**Phase 1: Skeleton.** Repo, `CLAUDE.md`, config, docker-compose (bot, worker, uploader, redis, postgres), DB + Alembic, `/start` + i18n (uz/ru/en), arq round-trip, `make_session.py`, the uploader connecting with the userbot, storage channels wired up: the bot receives a channel_post and logs the file_id, **`ReplyTarget` + the single send helper (section 2a)**, and an echo test that answers in the same topic. *Test: 3 languages; a file the userbot posts to a storage channel reaches the bot's handler; in my forum group, a message in General and in 3 different topics each gets its reply in the same topic.*

**Phase 2: Delivery core + YouTube.** Delivery ladder (cache → self-upload via userbot), pending deliveries, cache with storage records, egress budget, YouTube extractor, quality picker, MP3 with tags, progress, errors. *Test: 1080p video, a >50 MB file, Shorts, MP3, and a second request instantly from cache. Repeat all of it inside forum topics, including the quality picker.*

**Phase 3: Instagram + URL-send.** Reels, posts, carousels, stories/highlights with session rotation; the URL-send step; stats per method. *Test: each type, and confirm small items go via `url` with 0 egress.*

**Phase 4: Remaining core platforms: TikTok + Threads + Pinterest.** TikTok first (no-watermark video, slideshows, MP3), then Threads and Pinterest. Extractors (verify library support first), short links, URL-send. *Test: images, videos, multi-media posts, TikTok slideshow, all inside a forum topic too.*

**Phase 4b: Extra platforms (Tier 2).** Facebook, X/Twitter, Snapchat, Likee, VK, SoundCloud, Spotify (→ YouTube MP3), Reddit, Twitch clips, Vimeo. One module + tests each; `PLATFORMS_ENABLED` switch; add them to the health-check. *Test: one public sample link per platform; report which ones need cookies/proxy from Railway.*

**Phase 5: Helper-bot relay.** Registry, userbot conversation handling, correlation, validation, junk filtering, failover, admin commands, `RELAY_THRESHOLD_MB` routing. *Test with 2 real helper bots: large YouTube video via relay; disable one helper and confirm failover.*

**Phase 6: Music + Lyrics.** Shazam button, recognition from user-sent media via the inbox channel, full-MP3 fetch, song search, extract-MP3, lyrics (LRCLIB, 📝 buttons, `/lyrics`, pagination, `.lrc` file). *Test: recognize from a reel and from a voice note; search by name; lyrics for an Uzbek, a Russian and an English song; the .lrc file opens in a text editor with timestamps.*

**Phase 7: Inline + group settings.** Inline mode (links, music search, lyrics); group `/settings` (auto-download toggle, allowed topics, fallback behaviour). Topic routing already exists from Phase 1. *Test in a real forum group and via inline in a private chat.*

**Phase 8: Admin + monetization plumbing.** Admin panel, stats, broadcast, ban, mandatory sub, ad footer, Stars premium, health-check, `rebuild_cache`. *Test each flag on and off; rebuild the cache with a second test bot.*

**Phase 9: Deploy.** Mode A and Mode B, `DEPLOY.md`, webhook option, hardening. *Test: Mode A end-to-end, then Mode B on Railway.*

Start with Phase 1. Before writing code, give me (in Uzbek) a short plan for Phase 1 and the list of things you need from me (bot token, api_id/api_hash, the userbot account, channel IDs, etc.).
