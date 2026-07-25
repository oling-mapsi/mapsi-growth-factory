"""asset revision snapshots

Revision ID: 20260719_0022
Revises: 20260713_0021
Create Date: 2026-07-19 10:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0022"
down_revision = "20260713_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_revision_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content_asset_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("call_to_action", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("target_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("approved_content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("results", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_run_id"], ["campaign_runs.id"]),
        sa.ForeignKeyConstraint(["content_asset_id"], ["content_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if op.get_bind().dialect.name != "sqlite":
        for column in ("version", "status", "title", "subject", "content_html", "content_text", "excerpt", "call_to_action", "target_url", "content_hash", "approved_content_hash", "results"):
            op.alter_column("asset_revision_snapshots", column, server_default=None)


def downgrade() -> None:
    op.drop_table("asset_revision_snapshots")
