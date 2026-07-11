"""audience segmentation

Revision ID: 20260711_0005
Revises: 20260711_0004
Create Date: 2026-07-11 21:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0005"
down_revision = "20260711_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audience_segment_previews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("segment_id", sa.String(length=128), nullable=False),
        sa.Column("segment_label", sa.String(length=255), nullable=False),
        sa.Column("legal_basis", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("blocked_reasons", sa.JSON(), nullable=False),
        sa.Column("total_volume", sa.Integer(), nullable=False),
        sa.Column("eligible_volume", sa.Integer(), nullable=False),
        sa.Column("exclusions_by_reason", sa.JSON(), nullable=False),
        sa.Column("role_distribution", sa.JSON(), nullable=False),
        sa.Column("module_distribution", sa.JSON(), nullable=False),
        sa.Column("client_distribution", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audience_segment_audits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("preview_id", sa.String(length=36), sa.ForeignKey("audience_segment_previews.id"), nullable=False),
        sa.Column("contact_membership_id", sa.String(length=36), sa.ForeignKey("contact_memberships.id"), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("client_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audience_segment_audits")
    op.drop_table("audience_segment_previews")
