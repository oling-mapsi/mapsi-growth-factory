"""multichannel content assets

Revision ID: 20260711_0010
Revises: 20260711_0009
Create Date: 2026-07-12 03:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0010"
down_revision = "20260711_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_assets", sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("content_assets", sa.Column("audience_segment_id", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("approved_by", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_assets", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_assets", sa.Column("results", sa.JSON(), nullable=False, server_default="{}"))

    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("content_assets", "evidence_ids", server_default=None)
        op.alter_column("content_assets", "audience_segment_id", server_default=None)
        op.alter_column("content_assets", "content_hash", server_default=None)
        op.alter_column("content_assets", "approved_by", server_default=None)
        op.alter_column("content_assets", "results", server_default=None)


def downgrade() -> None:
    op.drop_column("content_assets", "results")
    op.drop_column("content_assets", "scheduled_at")
    op.drop_column("content_assets", "approved_at")
    op.drop_column("content_assets", "approved_by")
    op.drop_column("content_assets", "content_hash")
    op.drop_column("content_assets", "audience_segment_id")
    op.drop_column("content_assets", "evidence_ids")
