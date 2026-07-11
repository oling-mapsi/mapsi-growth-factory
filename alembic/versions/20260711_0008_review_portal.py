"""review portal

Revision ID: 20260711_0008
Revises: 20260711_0007
Create Date: 2026-07-12 00:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0008"
down_revision = "20260711_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.String(length=64), nullable=False),
        sa.Column("segment_id", sa.String(length=128), nullable=False),
        sa.Column("segment_label", sa.String(length=255), nullable=False),
        sa.Column("segment_version", sa.Integer(), nullable=False),
        sa.Column("audience_volume", sa.Integer(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("email_subject", sa.String(length=255), nullable=False),
        sa.Column("email_preheader", sa.String(length=255), nullable=False),
        sa.Column("email_html", sa.Text(), nullable=False),
        sa.Column("email_text", sa.Text(), nullable=False),
        sa.Column("quality_control", sa.JSON(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("approved_content_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_audience_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(length=255), nullable=False),
        sa.UniqueConstraint("campaign_run_id", name="uq_campaign_reviews_campaign_run_id"),
    )
    op.create_table(
        "review_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_review_id", sa.String(length=36), sa.ForeignKey("campaign_reviews.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_tokens")
    op.drop_table("campaign_reviews")
