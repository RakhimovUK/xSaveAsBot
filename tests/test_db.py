"""Runs the real Alembic migration on SQLite, then exercises the repo helpers."""

import os
import subprocess
import sys
from pathlib import Path

from app.db import repo
from app.db.models import User
from app.db.session import make_engine, make_sessionmaker

ROOT = Path(__file__).resolve().parent.parent


def _migrate(url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
    )


async def test_migration_and_repo(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'x.db').as_posix()}"
    _migrate(url)
    engine = make_engine(url)
    sm = make_sessionmaker(engine)
    async with sm() as s:
        u = await repo.touch_user(s, 42, "ali")
        assert u.lang is None
        await repo.set_user_lang(s, 42, "ru")
        g = await repo.touch_group(s, -100, "Forum", True)
        assert g.fallback_without_thread is False
        await s.commit()
    async with sm() as s:
        u = await s.get(User, 42)
        assert u.lang == "ru"
        await repo.touch_user(s, 42, "ali2")
        await s.commit()
    await engine.dispose()
