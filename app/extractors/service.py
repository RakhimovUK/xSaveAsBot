"""Per-platform fallback chains and file download (the `self` ladder step)."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.extractors import gallerydl, threads, ytdlp
from app.extractors.base import LocalFile, MediaInfo
from app.extractors.errors import ExtractError, UnsupportedError
from app.extractors.url_utils import UA

log = logging.getLogger(__name__)

# Platforms where yt-dlp often lacks images/carousels: gallery-dl is the second try.
GALLERY_FALLBACK = {"instagram", "pinterest", "tiktok", "twitter", "threads"}


def _rank(exc: ExtractError) -> int:
    """Prefer the most informative error when every extractor failed."""
    return 0 if isinstance(exc, UnsupportedError) else 1


async def probe(url: str, key: str, platform: str, settings: Settings) -> MediaInfo:
    errors: list[ExtractError] = []
    chain = []
    if platform == "threads":
        chain.append(lambda: threads.probe(url, key))
    else:
        chain.append(lambda: ytdlp.probe(url, key, platform, settings))
    if platform in GALLERY_FALLBACK:
        chain.append(lambda: gallerydl.probe(url, key, platform))
    for attempt in chain:
        try:
            return await attempt()
        except ExtractError as exc:
            log.info("probe step failed platform=%s: %s", platform, str(exc)[:200])
            errors.append(exc)
    raise max(errors, key=_rank)


async def _http_download(url: str, dest_dir: Path, index: int, ext_hint: str | None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        ext = ext_hint or urlsplit(url).path.rsplit(".", 1)[-1].lower()
        if not ext or len(ext) > 4:
            guessed = mimetypes.guess_extension(resp.headers.get("content-type", "").split(";")[0])
            ext = (guessed or ".bin").lstrip(".")
        path = dest_dir / f"{index:03d}.{ext}"
        with path.open("wb") as fh:
            async for chunk in resp.aiter_bytes(64 * 1024):
                fh.write(chunk)
    return path


async def fetch_files(
    info: MediaInfo | None,
    url: str,
    platform: str,
    variant: str | None,
    workdir: Path,
    settings: Settings,
) -> list[LocalFile]:
    """Download the media to `workdir` (costs egress). Direct CDN files over HTTP,
    everything else (YouTube, DASH/HLS, merges, MP3) through yt-dlp."""
    use_http = info is not None and platform != "youtube" and variant != "mp3" and info.all_direct
    if not use_http:
        return await ytdlp.download(url, workdir, settings, platform, variant)
    assert info is not None
    files: list[LocalFile] = []
    for index, item in enumerate(info.items, 1):
        path = await _http_download(item.url or "", workdir, index, item.ext)
        files.append(
            LocalFile(
                path=str(path),
                kind=item.kind,
                name=path.name,
                size=path.stat().st_size,
                duration=item.duration,
                width=item.width,
                height=item.height,
                title=info.title,
                performer=info.uploader,
            )
        )
    return files
