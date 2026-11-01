"""initial: users, groups, media_cache, settings

Revision ID: 0001
Revises:
Create Date: 2026-11-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(64)),
        sa.Column("lang", sa.String(8)),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("premium_until", sa.DateTime(timezone=True)),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("referrer", sa.BigInteger()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "groups",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("title", sa.String(255)),
        sa.Column("is_forum", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lang", sa.String(8)),
        sa.Column("auto_download", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_topics", sa.JSON()),
        sa.Column(
            "fallback_without_thread", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "media_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("bot_file_ids", sa.JSON(), nullable=False),
        sa.Column("storage_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_message_ids", sa.JSON(), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("size", sa.BigInteger()),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_media_cache_key", "media_cache", ["key"], unique=True)
    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_media_cache_key", table_name="media_cache")
    op.drop_table("media_cache")
    op.drop_table("groups")
    op.drop_table("users")
