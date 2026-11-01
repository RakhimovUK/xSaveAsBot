"""Find links in text, detect the platform and build canonical cache keys.

Key scheme (variant is appended by the caller, e.g. `yt:<id>:720p`):
  yt:<id>  ig:<code>  ig:story:<user>:<id>  tt:<id>  th:<code>  pin:<id>  x:<id>
  fb:/sn:/lk:/sc:/tw:<hash>  vk:<owner_id>  rd:<id>  vm:<id>  sp:<id>
Short links (vm.tiktok.com, pin.it, t.co, ...) have key=None until resolved.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
TRAILING = ".,;:!?)]}»”'\""

CORE_PLATFORMS = ("youtube", "instagram", "tiktok", "threads", "pinterest")
EXTRA_PLATFORMS = (
    "facebook",
    "twitter",
    "snapchat",
    "likee",
    "vk",
    "soundcloud",
    "spotify",
    "reddit",
    "twitch",
    "vimeo",
)
ALL_PLATFORMS = CORE_PLATFORMS + EXTRA_PLATFORMS


def tier_of(platform: str) -> str:
    return "core" if platform in CORE_PLATFORMS else "extra"


@dataclass(frozen=True)
class Detected:
    platform: str
    key: str | None  # None: short link, resolve first
    url: str


def find_urls(text: str | None) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(TRAILING)
        if url not in urls:
            urls.append(url)
    return urls


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:12]


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    for prefix in ("www.", "m.", "mobile.", "music."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


YT_ID = re.compile(r"[\w-]{11}")


def detect(url: str) -> Detected | None:
    parts = urlsplit(url)
    host = _host(parts.netloc)
    path = parts.path or "/"
    qs = parse_qs(parts.query)

    # YouTube
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        vid = None
        if host == "youtu.be":
            vid = path.strip("/")[:11]
        elif path == "/watch":
            vid = (qs.get("v") or [None])[0]
        else:
            m = re.match(r"^/(?:shorts|live|embed|v)/([\w-]{11})", path)
            vid = m.group(1) if m else None
        if vid and YT_ID.fullmatch(vid):
            return Detected("youtube", f"yt:{vid}", f"https://www.youtube.com/watch?v={vid}")
        return None

    # Instagram
    if host in {"instagram.com", "instagr.am"}:
        if path.startswith("/share/"):
            return Detected("instagram", None, url)
        m = re.search(r"/(?:p|reel|reels|tv)/([\w-]+)", path)
        if m:
            return Detected("instagram", f"ig:{m.group(1)}", f"https://www.instagram.com{path}")
        m = re.match(r"^/stories/highlights/(\d+)", path)
        if m:
            return Detected("instagram", f"ig:hl:{m.group(1)}", f"https://www.instagram.com{path}")
        m = re.match(r"^/stories/([\w.]+)/(\d+)", path)
        if m:
            key = f"ig:story:{m.group(1)}:{m.group(2)}"
            return Detected("instagram", key, f"https://www.instagram.com{path}")
        return None

    # TikTok
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        if host in {"vm.tiktok.com", "vt.tiktok.com"} or path.startswith("/t/"):
            return Detected("tiktok", None, url)
        m = re.search(r"/(?:video|photo)/(\d+)", path) or re.match(r"^/v/(\d+)", path)
        if m:
            return Detected("tiktok", f"tt:{m.group(1)}", f"https://www.tiktok.com{path}")
        return None

    # Threads
    if host in {"threads.net", "threads.com"}:
        m = re.search(r"/post/([\w-]+)", path)
        if m:
            return Detected("threads", f"th:{m.group(1)}", f"https://www.threads.com{path}")
        return None

    # Pinterest
    if host == "pin.it":
        return Detected("pinterest", None, url)
    if re.fullmatch(r"([a-z]{2}\.)?pinterest\.[a-z.]+", host):
        m = re.search(r"/pin/(\d+)", path)
        if m:
            return Detected(
                "pinterest", f"pin:{m.group(1)}", f"https://www.pinterest.com/pin/{m.group(1)}/"
            )
        return None

    # X / Twitter
    if host == "t.co":
        return Detected("twitter", None, url)
    if host in {"x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"}:
        m = re.search(r"/status(?:es)?/(\d+)", path)
        if m:
            return Detected("twitter", f"x:{m.group(1)}", f"https://x.com/i/status/{m.group(1)}")
        return None

    # Facebook
    if host in {"facebook.com", "fb.watch", "fb.com", "web.facebook.com"}:
        vid = (qs.get("v") or [None])[0]
        if vid:
            return Detected("facebook", f"fb:{vid}", f"https://www.facebook.com/watch/?v={vid}")
        if path.strip("/"):
            return Detected("facebook", f"fb:{_hash(host + path)}", url)
        return None

    # Snapchat / Likee
    if host.endswith("snapchat.com") and path.strip("/"):
        return Detected("snapchat", f"sn:{_hash(path)}", url)
    if host in {"likee.video", "likee.com", "l.likee.video"} and path.strip("/"):
        return Detected("likee", f"lk:{_hash(path)}", url)

    # VK
    if host in {"vk.com", "vk.ru", "vkvideo.ru"}:
        m = re.search(r"(?:video|clip)(-?\d+_\d+)", parts.path + "?" + parts.query)
        if m:
            return Detected("vk", f"vk:{m.group(1)}", f"https://vk.com/video{m.group(1)}")
        return None

    # SoundCloud
    if host == "on.soundcloud.com":
        return Detected("soundcloud", None, url)
    if host == "soundcloud.com" and len([s for s in path.split("/") if s]) >= 2:
        return Detected("soundcloud", f"sc:{_hash(path.lower())}", f"https://soundcloud.com{path}")

    # Spotify (tracks only; metadata -> YouTube match arrives with the music phase)
    if host == "spotify.link":
        return Detected("spotify", None, url)
    if host == "open.spotify.com":
        m = re.search(r"/track/(\w+)", path)
        if m:
            return Detected(
                "spotify", f"sp:{m.group(1)}", f"https://open.spotify.com/track/{m.group(1)}"
            )
        return None

    # Reddit
    if host in {"reddit.com", "old.reddit.com"}:
        m = re.search(r"/comments/(\w+)", path)
        if m:
            return Detected("reddit", f"rd:{m.group(1)}", url)
        return None
    if host == "redd.it" and path.strip("/"):
        return Detected("reddit", f"rd:{path.strip('/')}", url)
    if host == "v.redd.it" and path.strip("/"):
        return Detected("reddit", f"rd:{_hash(path)}", url)

    # Twitch clips
    if host == "clips.twitch.tv" and path.strip("/"):
        slug = path.strip("/").split("/")[0]
        return Detected("twitch", f"tw:{slug}", f"https://clips.twitch.tv/{slug}")
    if host == "twitch.tv":
        m = re.search(r"/clip/([\w-]+)", path)
        if m:
            return Detected("twitch", f"tw:{m.group(1)}", f"https://clips.twitch.tv/{m.group(1)}")
        return None

    # Vimeo
    if host in {"vimeo.com", "player.vimeo.com"}:
        m = re.search(r"/(?:video/)?(\d{5,})", path)
        if m:
            return Detected("vimeo", f"vm:{m.group(1)}", f"https://vimeo.com/{m.group(1)}")
        return None

    return None


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


async def resolve_short(url: str) -> str:
    """Follow redirects of a short link and return the final URL."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=12, headers={"User-Agent": UA}
    ) as client:
        try:
            resp = await client.head(url)
            if resp.status_code >= 400 or str(resp.url) == url:
                resp = await client.get(url)
        except httpx.HTTPError:
            return url
        return str(resp.url)


async def detect_resolved(url: str) -> Detected | None:
    detected = detect(url)
    if detected is None or detected.key is not None:
        return detected
    final = await resolve_short(detected.url)
    again = detect(final)
    return again if again is not None and again.key is not None else None
