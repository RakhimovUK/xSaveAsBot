from app.bot.media_utils import extract_file, key_tag, parse_key
from app.media.testfile import write_png


def test_key_roundtrip():
    assert parse_key(f"Some caption\n{key_tag('yt:dQw4w9WgXcQ:720p')}") == "yt:dQw4w9WgXcQ:720p"
    assert parse_key("no tag") is None
    assert parse_key(None) is None


def test_extract_largest_photo(msg_factory):
    m = msg_factory(
        chat_type="channel",
        text=None,
        photo=[
            {"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
            {"file_id": "big", "file_unique_id": "b", "width": 320, "height": 320, "file_size": 99},
        ],
    )
    f = extract_file(m)
    assert (f.kind, f.file_id, f.size) == ("photo", "big", 99)


def test_extract_none_for_text(msg_factory):
    assert extract_file(msg_factory()) is None


def test_png_is_valid(tmp_path):
    data = write_png(tmp_path / "x.png", 4, 4).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")
