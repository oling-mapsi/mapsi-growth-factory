"""mautic campaign publication

Revision ID: 20260711_0009
Revises: 20260711_0008
Create Date: 2026-07-12 01:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0009"
down_revision = "20260711_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mautic_campaign_publications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("segment_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mautic_email_id", sa.String(length=64), nullable=False),
        sa.Column("mautic_segment_id", sa.String(length=64), nullable=False),
        sa.Column("mautic_campaign_id", sa.String(length=64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("target_instance_ids", sa.JSON(), nullable=False),
        sa.Column("target_client_ids", sa.JSON(), nullable=False),
        sa.Column("targeted_contacts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_run_id",
            "content_version",
            "segment_version",
            name="uq_mautic_campaign_publication_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("mautic_campaign_publications")
