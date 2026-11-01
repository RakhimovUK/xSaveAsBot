"""downloads and helper_bots

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("platform", sa.String(32)),
        sa.Column("key", sa.String(255)),
        sa.Column("method", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_class", sa.String(32)),
        sa.Column("bytes_egress", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_downloads_user_id", "downloads", ["user_id"])
    op.create_index("ix_downloads_platform", "downloads", ["platform"])
    op.create_index("ix_downloads_created_at", "downloads", ["created_at"])
    op.create_table(
        "helper_bots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("platforms", sa.String(255), nullable=False, server_default="all"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("helper_bots")
    op.drop_index("ix_downloads_created_at", table_name="downloads")
    op.drop_index("ix_downloads_platform", table_name="downloads")
    op.drop_index("ix_downloads_user_id", table_name="downloads")
    op.drop_table("downloads")
