"""multichannel assets model

Revision ID: 20260711_0012
Revises: 20260711_0011
Create Date: 2026-07-11 23:50:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0012"
down_revision = "20260711_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_assets", sa.Column("locale", sa.String(length=16), nullable=False, server_default="fr-FR"))
    op.add_column("content_assets", sa.Column("subject", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("content_html", sa.Text(), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("content_text", sa.Text(), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("excerpt", sa.Text(), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("call_to_action", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("target_url", sa.String(length=1024), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("content_assets", sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("content_assets", sa.Column("approved_content_hash", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_assets", sa.Column("external_publication_id", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("external_publication_url", sa.String(length=1024), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("last_error", sa.Text(), nullable=False, server_default=""))
    op.add_column("content_assets", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("publications", sa.Column("content_asset_id", sa.String(length=36), nullable=False, server_default=""))
    op.add_column("publications", sa.Column("external_url", sa.String(length=1024), nullable=False, server_default=""))

    op.execute("UPDATE content_assets SET content_html = body WHERE content_html = ''")
    op.execute("UPDATE content_assets SET content_text = body WHERE content_text = ''")
    op.execute("UPDATE content_assets SET subject = title WHERE subject = '' AND channel = 'mautic'")
    op.execute("UPDATE content_assets SET source_evidence_ids = evidence_ids WHERE source_evidence_ids = '[]'")
    op.execute("UPDATE content_assets SET content_version = revision WHERE content_version = 1")
    op.execute(
        """
        UPDATE content_assets
        SET approved_content_hash = content_hash
        WHERE approved_content_hash = ''
          AND approved_at IS NOT NULL
          AND content_hash <> ''
        """
    )
    op.execute(
        """
        UPDATE content_assets
        SET external_publication_id = ''
        WHERE external_publication_id IS NULL
        """
    )

    if op.get_bind().dialect.name != "sqlite":
        for table, column in [
            ("content_assets", "locale"),
            ("content_assets", "subject"),
            ("content_assets", "content_html"),
            ("content_assets", "content_text"),
            ("content_assets", "excerpt"),
            ("content_assets", "call_to_action"),
            ("content_assets", "target_url"),
            ("content_assets", "source_evidence_ids"),
            ("content_assets", "content_version"),
            ("content_assets", "approved_content_hash"),
            ("content_assets", "external_publication_id"),
            ("content_assets", "external_publication_url"),
            ("content_assets", "last_error"),
            ("content_assets", "retry_count"),
            ("publications", "content_asset_id"),
            ("publications", "external_url"),
        ]:
            op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    op.drop_column("publications", "external_url")
    op.drop_column("publications", "content_asset_id")

    op.drop_column("content_assets", "retry_count")
    op.drop_column("content_assets", "last_error")
    op.drop_column("content_assets", "external_publication_url")
    op.drop_column("content_assets", "external_publication_id")
    op.drop_column("content_assets", "published_at")
    op.drop_column("content_assets", "approved_content_hash")
    op.drop_column("content_assets", "content_version")
    op.drop_column("content_assets", "source_evidence_ids")
    op.drop_column("content_assets", "target_url")
    op.drop_column("content_assets", "call_to_action")
    op.drop_column("content_assets", "excerpt")
    op.drop_column("content_assets", "content_text")
    op.drop_column("content_assets", "content_html")
    op.drop_column("content_assets", "subject")
    op.drop_column("content_assets", "locale")
