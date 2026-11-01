from app.extractors import errors, threads, ytdlp
from app.extractors.errors import classify, is_relayable


def test_classify_errors():
    assert isinstance(
        classify("Sign in to confirm you’re not a bot. This helps protect our community"),
        errors.BotCheckError,
    )
    assert isinstance(classify("ERROR: Unsupported URL: https://x"), errors.UnsupportedError)
    assert isinstance(classify("This video is private"), errors.PrivateError)
    assert isinstance(classify("Account authentication is required"), errors.LoginRequiredError)
    assert isinstance(classify("HTTP Error 404: Not Found"), errors.NotFoundError)
    assert isinstance(classify("Read timed out"), errors.TemporaryError)
    assert classify("weird").code == "generic"


def test_relayable():
    assert is_relayable(errors.BotCheckError("x"))
    assert is_relayable(errors.LoginRequiredError("x"))
    assert not is_relayable(errors.PrivateError("x"))
    assert not is_relayable(errors.NotFoundError("x"))
    assert not is_relayable(errors.TooLongError("x"))


def test_info_to_media_single_reel_has_direct_url():
    info = {
        "id": "A",
        "title": "Reel",
        "description": "caption text",
        "ext": "mp4",
        "url": "https://cdn.example/v.mp4",
        "protocol": "https",
        "vcodec": "h264",
        "acodec": "aac",
        "width": 720,
        "height": 1280,
        "duration": 12.5,
        "filesize_approx": 1_000_000,
    }
    media = ytdlp.info_to_media("instagram", "ig:A", "https://i/A", info)
    assert media.caption == "caption text" and media.duration == 12.5
    [item] = media.items
    assert item.kind == "video" and item.url == "https://cdn.example/v.mp4"
    assert item.size == 1_000_000 and media.all_direct


def test_info_to_media_carousel_and_images():
    info = {
        "title": "post",
        "entries": [
            {"ext": "jpg", "url": "https://cdn/1.jpg", "protocol": "https"},
            {
                "ext": "mp4",
                "url": "https://cdn/2.mp4",
                "protocol": "https",
                "vcodec": "h264",
                "acodec": "aac",
            },
        ],
    }
    media = ytdlp.info_to_media("instagram", "ig:B", "u", info)
    assert [i.kind for i in media.items] == ["photo", "video"]
    assert media.all_direct and media.total_size is None  # unknown sizes


def test_merge_formats_are_not_direct():
    info = {
        "title": "t",
        "ext": "mp4",
        "requested_formats": [{}, {}],
        "url": "https://cdn/x",
        "protocol": "https",
        "vcodec": "vp9",
    }
    assert not ytdlp.info_to_media("youtube", "yt:x", "u", info).all_direct


def test_hls_is_not_direct():
    info = {"ext": "mp4", "url": "https://cdn/x.m3u8", "protocol": "m3u8_native", "vcodec": "h264"}
    assert not ytdlp.info_to_media("tiktok", "tt:1", "u", info).all_direct


def test_youtube_picker_formats():
    fmts = [
        {"vcodec": "avc1", "acodec": "none", "height": 360, "filesize": 10_000_000},
        {"vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 40_000_000},
        {"vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 90_000_000},
        {"vcodec": "none", "acodec": "mp4a", "filesize": 3_000_000},
    ]
    options = ytdlp.youtube_formats({"formats": fmts})
    assert [o.variant for o in options] == ["360p", "720p", "1080p"]
    assert options[1].size == 43_000_000


def test_format_selector_for_variants():
    assert ytdlp._format_for("mp3") == ("bestaudio/best", True)
    fmt, audio = ytdlp._format_for("720p")
    assert "height<=720" in fmt and not audio
    assert ytdlp._format_for("best") == ("bv*+ba/b", False)


THREADS_HTML = (
    '..."code":"ABC123","media":{"carousel_media":['
    '{"image_versions2":{"candidates":[{"width":1080,"height":1350,"url":"https:\\/\\/cdn.x\\/1.jpg?a=1\\u0026b=2"}]}},'
    '{"image_versions2":{"candidates":[{"width":720,"height":1280,"url":"https:\\/\\/cdn.x\\/poster.jpg"}]},'
    '"video_versions":[{"type":101,"url":"https:\\/\\/cdn.x\\/2.mp4"}]}'
    "]}"
)


def test_threads_parser_photo_and_video():
    items = threads.parse_page(THREADS_HTML, "ABC123")
    assert [i.kind for i in items] == ["photo", "video"]
    assert items[0].url == "https://cdn.x/1.jpg?a=1&b=2"
    assert items[1].url == "https://cdn.x/2.mp4"
