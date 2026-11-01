from app.config import Settings, normalize_db_url


def test_railway_db_url_gets_asyncpg_driver():
    assert normalize_db_url("postgresql://u:p@h:5432/d") == "postgresql+asyncpg://u:p@h:5432/d"
    assert normalize_db_url("postgres://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"
    assert normalize_db_url("sqlite+aiosqlite:///x.db") == "sqlite+aiosqlite:///x.db"


def test_parsing(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1, 2,3")
    monkeypatch.setenv("USERBOT_SESSIONS", "aaa,bbb")
    monkeypatch.setenv("PLATFORMS_ENABLED", "YouTube,tiktok")
    monkeypatch.setenv("STORAGE_CHANNELS", '{"youtube": -1001, "music": -1002}')
    monkeypatch.setenv("STORAGE_CHANNEL_DEFAULT", "-1009")
    monkeypatch.setenv("INBOX_CHANNEL", "")
    s = Settings(_env_file=None)
    assert s.admin_ids == [1, 2, 3]
    assert s.userbot_sessions == ["aaa", "bbb"]
    assert s.platforms_enabled == ["youtube", "tiktok"]
    assert s.storage_channel_for("youtube") == -1001
    assert s.storage_channel_for("instagram") == -1009
    assert s.all_storage_channel_ids == {-1001, -1002, -1009}
    assert s.inbox_channel is None
    assert s.is_admin(2) and not s.is_admin(None)
