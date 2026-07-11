"""linkedin publisher

Revision ID: 20260711_0011
Revises: 20260711_0010
Create Date: 2026-07-12 05:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0011"
down_revision = "20260711_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linkedin_oauth_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="linkedin"),
        sa.Column("subject", sa.String(length=64), nullable=False, server_default="organization"),
        sa.Column("access_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_linkedin_oauth_provider_subject"),
    )
    op.create_table(
        "linkedin_publications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("content_asset_id", sa.String(length=36), sa.ForeignKey("content_assets.id"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("organization_urn", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("linkedin_post_urn", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="mock"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_asset_id", "content_hash", name="uq_linkedin_publications_asset_hash"),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("linkedin_oauth_tokens", "provider", server_default=None)
        op.alter_column("linkedin_oauth_tokens", "subject", server_default=None)
        op.alter_column("linkedin_oauth_tokens", "access_token", server_default=None)
        op.alter_column("linkedin_oauth_tokens", "refresh_token", server_default=None)
        op.alter_column("linkedin_oauth_tokens", "scope", server_default=None)
        op.alter_column("linkedin_publications", "organization_urn", server_default=None)
        op.alter_column("linkedin_publications", "linkedin_post_urn", server_default=None)
        op.alter_column("linkedin_publications", "status", server_default=None)
        op.alter_column("linkedin_publications", "mode", server_default=None)
        op.alter_column("linkedin_publications", "idempotency_key", server_default=None)
        op.alter_column("linkedin_publications", "last_error", server_default=None)
        op.alter_column("linkedin_publications", "metrics", server_default=None)


def downgrade() -> None:
    op.drop_table("linkedin_publications")
    op.drop_table("linkedin_oauth_tokens")
