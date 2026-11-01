import pytest

from app.extractors.url_utils import detect, find_urls, tier_of


@pytest.mark.parametrize(
    ("url", "platform", "key"),
    [
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "youtube", "yt:dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x", "youtube", "yt:dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "youtube", "yt:dQw4w9WgXcQ"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "yt:dQw4w9WgXcQ"),
        ("https://www.instagram.com/reel/De9oyINo2eW/?cplk=MXh0", "instagram", "ig:De9oyINo2eW"),
        ("https://instagr.am/p/ABC_def-1/", "instagram", "ig:ABC_def-1"),
        (
            "https://www.instagram.com/stories/some.user/3141592/",
            "instagram",
            "ig:story:some.user:3141592",
        ),
        ("https://www.instagram.com/stories/highlights/1789/", "instagram", "ig:hl:1789"),
        (
            "https://www.tiktok.com/@scout2015/video/6718335390845095173",
            "tiktok",
            "tt:6718335390845095173",
        ),
        ("https://www.tiktok.com/@u/photo/6718335390845095173", "tiktok", "tt:6718335390845095173"),
        ("https://www.threads.net/@zuck/post/C8-B0EzS13_", "threads", "th:C8-B0EzS13_"),
        (
            "https://www.pinterest.com/pin/664281013778109217/",
            "pinterest",
            "pin:664281013778109217",
        ),
        ("https://x.com/SpaceX/status/1588281931231920130", "twitter", "x:1588281931231920130"),
        ("https://twitter.com/a/status/12345", "twitter", "x:12345"),
        ("https://www.facebook.com/watch/?v=10153231379946729", "facebook", "fb:10153231379946729"),
        ("https://vimeo.com/76979871", "vimeo", "vm:76979871"),
        ("https://vk.com/video-22822305_456239018", "vk", "vk:-22822305_456239018"),
        ("https://clips.twitch.tv/SomeSlug-abc", "twitch", "tw:SomeSlug-abc"),
        ("https://www.reddit.com/r/videos/comments/6rrwyj/title/", "reddit", "rd:6rrwyj"),
        (
            "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=x",
            "spotify",
            "sp:4uLU6hMCjMI75M1A2tKUQC",
        ),
    ],
)
def test_detect_keys(url, platform, key):
    d = detect(url)
    assert d is not None
    assert (d.platform, d.key) == (platform, key)


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://vm.tiktok.com/ZMabc/", "tiktok"),
        ("https://vt.tiktok.com/ZSabc/", "tiktok"),
        ("https://pin.it/4abc", "pinterest"),
        ("https://t.co/abc", "twitter"),
        ("https://www.instagram.com/share/reel/BAbc/", "instagram"),
    ],
)
def test_short_links_need_resolving(url, platform):
    d = detect(url)
    assert d is not None and d.key is None and d.platform == platform


def test_same_post_same_key_regardless_of_tracking_params():
    a = detect("https://www.instagram.com/reel/AAA/?igsh=1")
    b = detect("https://instagram.com/reel/AAA/?utm_source=x")
    assert a.key == b.key == "ig:AAA"


def test_unsupported():
    assert detect("https://example.com/video/1") is None
    assert detect("https://www.youtube.com/") is None


def test_find_urls_strips_punctuation_and_dedupes():
    text = "look https://youtu.be/dQw4w9WgXcQ, and (https://vimeo.com/76979871). again https://youtu.be/dQw4w9WgXcQ"
    assert find_urls(text) == ["https://youtu.be/dQw4w9WgXcQ", "https://vimeo.com/76979871"]


def test_tiers():
    assert tier_of("youtube") == "core" and tier_of("vimeo") == "extra"
