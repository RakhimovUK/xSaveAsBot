"""yt-dlp wrapper: probe (metadata + direct URLs) and download."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import Settings
from app.extractors.base import FormatOption, LocalFile, MediaInfo, MediaItem
from app.extractors.errors import ExtractError, classify

log = logging.getLogger(__name__)

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic"}
AUDIO_EXTS = {"mp3", "m4a", "opus", "ogg", "aac", "flac", "wav"}
SKIP_SUFFIXES = {".part", ".ytdl", ".json", ".tmp", ".temp"}
PICKER_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)


def _cookie_file(settings: Settings, platform: str) -> str | None:
    if platform == "youtube" and settings.yt_cookies_path:
        return settings.yt_cookies_path if Path(settings.yt_cookies_path).is_file() else None
    if platform == "instagram":
        folder = Path(settings.instagram_sessions_dir)
        files = list(folder.glob("*.txt")) if folder.is_dir() else []
        return str(random.choice(files)) if files else None
    return None


def _proxy(settings: Settings, platform: str) -> str | None:
    return getattr(settings, f"proxy_url_{platform}", "") or None


def build_opts(settings: Settings, platform: str, **extra: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
        "extractor_retries": 2,
    }
    if cookies := _cookie_file(settings, platform):
        opts["cookiefile"] = cookies
    if proxy := _proxy(settings, platform):
        opts["proxy"] = proxy
    opts.update(extra)
    return opts


def _extract_sync(url: str, opts: dict[str, Any], download: bool) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=download)
        return ydl.sanitize_info(info)


async def probe_raw(url: str, settings: Settings, platform: str) -> dict[str, Any]:
    opts = build_opts(settings, platform, format="b/bv*+ba/best", skip_download=True)
    try:
        return await asyncio.to_thread(_extract_sync, url, opts, False)
    except Exception as exc:  # DownloadError / ExtractorError / network
        raise classify(str(exc)) from exc


def _kind_of(entry: dict[str, Any]) -> str:
    ext = (entry.get("ext") or "").lower()
    if ext in IMAGE_EXTS:
        return "photo"
    if entry.get("vcodec") in (None, "none") and entry.get("acodec") not in (None, "none"):
        return "audio"
    if ext in AUDIO_EXTS and not entry.get("height"):
        return "audio"
    return "video"


def _direct_url(entry: dict[str, Any]) -> str | None:
    """A plain downloadable file URL (not HLS/DASH, not a split audio+video pair)."""
    if entry.get("requested_formats"):
        return None
    url = entry.get("url")
    protocol = (entry.get("protocol") or "").lower()
    if url and protocol in ("https", "http", ""):
        return url
    return None


def _entry_item(entry: dict[str, Any]) -> MediaItem:
    return MediaItem(
        kind=_kind_of(entry),
        url=_direct_url(entry),
        ext=entry.get("ext"),
        size=entry.get("filesize") or entry.get("filesize_approx"),
        width=entry.get("width"),
        height=entry.get("height"),
        duration=entry.get("duration"),
    )


def youtube_formats(info: dict[str, Any]) -> list[FormatOption]:
    formats = info.get("formats") or []
    audio_size = max(
        (
            f.get("filesize") or f.get("filesize_approx") or 0
            for f in formats
            if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
        ),
        default=0,
    )
    options: list[FormatOption] = []
    for height in PICKER_HEIGHTS:
        candidates = [
            f
            for f in formats
            if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) <= height
        ]
        if not candidates:
            continue
        best_h = max(f.get("height") or 0 for f in candidates)
        if best_h != height and height != PICKER_HEIGHTS[0]:
            continue  # only offer heights that really exist
        pick = max(
            (f for f in candidates if (f.get("height") or 0) == best_h),
            key=lambda f: f.get("filesize") or f.get("filesize_approx") or 0,
        )
        video_size = pick.get("filesize") or pick.get("filesize_approx")
        size = (video_size + audio_size) if video_size else None
        if not any(o.height == best_h for o in options):
            options.append(FormatOption(f"{best_h}p", best_h, size))
    return options


def info_to_media(platform: str, key: str, url: str, info: dict[str, Any]) -> MediaInfo:
    entries = [e for e in (info.get("entries") or []) if e]
    items = [_entry_item(e) for e in entries] if entries else [_entry_item(info)]
    caption = info.get("description") or info.get("title")
    media = MediaInfo(
        platform=platform,
        key=key,
        source_url=url,
        title=info.get("track") or info.get("title"),
        caption=caption,
        uploader=info.get("artist") or info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        items=items,
        raw=info,
    )
    if platform == "youtube":
        media.formats = youtube_formats(info)
    return media


async def probe(url: str, key: str, platform: str, settings: Settings) -> MediaInfo:
    return info_to_media(platform, key, url, await probe_raw(url, settings, platform))


def _format_for(variant: str | None) -> tuple[str, bool]:
    """(yt-dlp format string, audio_only)."""
    if variant == "mp3":
        return "bestaudio/best", True
    if variant and variant.endswith("p") and variant[:-1].isdigit():
        h = int(variant[:-1])
        return f"bv*[height<={h}]+ba/b[height<={h}]/b", False
    return "bv*+ba/b", False


def _download_sync(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=True))


def _local_file(path: Path, info: dict[str, Any], audio_only: bool) -> LocalFile:
    ext = path.suffix.lstrip(".").lower()
    kind = (
        "photo" if ext in IMAGE_EXTS else "audio" if (audio_only or ext in AUDIO_EXTS) else "video"
    )
    title = info.get("track") or info.get("title")
    performer = info.get("artist") or info.get("uploader") or info.get("channel")
    name = path.name
    if kind == "audio" and title:
        safe = "".join(
            c for c in f"{performer + ' - ' if performer else ''}{title}" if c not in '\\/:*?"<>|'
        )
        name = f"{safe[:120]}.{ext}"
    return LocalFile(
        path=str(path),
        kind=kind,
        name=name,
        size=path.stat().st_size,
        duration=info.get("duration"),
        width=info.get("width"),
        height=info.get("height"),
        title=title,
        performer=performer,
    )


async def download(
    url: str, outdir: Path, settings: Settings, platform: str, variant: str | None
) -> list[LocalFile]:
    fmt, audio_only = _format_for(variant)
    opts = build_opts(
        settings,
        platform,
        format=fmt,
        outtmpl=str(outdir / "%(autonumber)03d_%(id)s.%(ext)s"),
        merge_output_format="mp4",
        noplaylist=False,
    )
    if audio_only:
        opts["writethumbnail"] = True
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ]
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        info = await asyncio.to_thread(_download_sync, url, opts)
    except (DownloadError, ExtractError) as exc:
        raise classify(str(exc)) from exc
    except Exception as exc:
        raise classify(str(exc)) from exc
    files = sorted(
        p
        for p in outdir.iterdir()
        if p.is_file()
        and p.suffix.lower() not in SKIP_SUFFIXES
        and not (audio_only and p.suffix == ".jpg")
    )
    if not files:
        raise ExtractError("yt-dlp produced no files")
    first = (info.get("entries") or [info])[0] or info
    return [_local_file(p, first, audio_only) for p in files]
