"""mapsi site publisher

Revision ID: 20260712_0018
Revises: 20260712_0017
Create Date: 2026-07-12 19:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_0018"
down_revision = "20260712_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapsi_news_publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_run_id", sa.String(length=36), nullable=False),
        sa.Column("content_asset_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=190), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="mock"),
        sa.Column("publication_mode_requested", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("publication_mode_executed", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("publisher_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("publication_status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("preview_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("public_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("public_slug", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("draft_revision_number", sa.Integer(), nullable=True),
        sa.Column("published_revision_number", sa.Integer(), nullable=True),
        sa.Column("published_content_version", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unpublished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_run_id"], ["campaign_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_asset_id", "content_hash", name="uq_mapsi_news_publications_asset_hash"),
        sa.UniqueConstraint("external_id", name="uq_mapsi_news_publications_external_id"),
    )
    if op.get_bind().dialect.name != "sqlite":
        for column in (
            "external_id",
            "content_hash",
            "status",
            "mode",
            "publication_mode_requested",
            "publication_mode_executed",
            "publisher_type",
            "publication_status",
            "idempotency_key",
            "preview_url",
            "public_url",
            "public_slug",
            "last_error",
            "metrics",
        ):
            op.alter_column("mapsi_news_publications", column, server_default=None)


def downgrade() -> None:
    op.drop_table("mapsi_news_publications")
