"""oling publication state consistency

Revision ID: 20260712_0014
Revises: 20260712_0013
Create Date: 2026-07-12 12:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_0014"
down_revision = "20260712_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oling_news_publications",
        sa.Column("publication_mode_requested", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "oling_news_publications",
        sa.Column("publication_mode_executed", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "oling_news_publications",
        sa.Column("publisher_type", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "oling_news_publications",
        sa.Column("publication_status", sa.String(length=32), nullable=False, server_default="DRAFT"),
    )

    op.execute(
        """
        UPDATE oling_news_publications
        SET publication_mode_requested = CASE
                WHEN status = 'published' THEN 'publish'
                WHEN status = 'unpublished' THEN 'publish'
                ELSE 'preview'
            END,
            publication_mode_executed = CASE
                WHEN mode = 'mock' THEN 'sandbox'
                WHEN mode = 'preview-only' THEN 'preview'
                WHEN status = 'published' THEN 'live'
                ELSE 'preview'
            END,
            publisher_type = CASE
                WHEN mode = 'mock' THEN 'oling_mock'
                ELSE 'oling_api'
            END,
            publication_status = UPPER(status)
        """
    )

    if op.get_bind().dialect.name != "sqlite":
        for column in (
            "publication_mode_requested",
            "publication_mode_executed",
            "publisher_type",
            "publication_status",
        ):
            op.alter_column("oling_news_publications", column, server_default=None)


def downgrade() -> None:
    op.drop_column("oling_news_publications", "publication_status")
    op.drop_column("oling_news_publications", "publisher_type")
    op.drop_column("oling_news_publications", "publication_mode_executed")
    op.drop_column("oling_news_publications", "publication_mode_requested")
