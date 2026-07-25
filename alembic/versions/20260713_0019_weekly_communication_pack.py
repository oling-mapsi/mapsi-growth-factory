"""weekly communication pack

Revision ID: 20260713_0019
Revises: 20260712_0018
Create Date: 2026-07-13 10:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0019"
down_revision = "20260712_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaign_runs", sa.Column("campaign_type", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("campaign_runs", sa.Column("weekly_pack_id", sa.String(length=36), nullable=False, server_default=""))
    op.add_column("campaign_runs", sa.Column("week_reference", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("campaign_runs", sa.Column("week_year", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaign_runs", sa.Column("week_number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("campaign_runs", sa.Column("pilot_mode", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "weekly_communication_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("week_reference", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NOT_STARTED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("campaign_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("global_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("operational_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("pilot_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "week_number", name="uq_weekly_communication_packs_year_week"),
    )
    if op.get_bind().dialect.name != "sqlite":
        for column in ("campaign_type", "weekly_pack_id", "week_reference", "week_year", "week_number", "pilot_mode"):
            op.alter_column("campaign_runs", column, server_default=None)
        for column in ("status", "campaign_ids", "global_summary", "operational_errors", "pilot_mode"):
            op.alter_column("weekly_communication_packs", column, server_default=None)


def downgrade() -> None:
    op.drop_table("weekly_communication_packs")
    op.drop_column("campaign_runs", "pilot_mode")
    op.drop_column("campaign_runs", "week_number")
    op.drop_column("campaign_runs", "week_year")
    op.drop_column("campaign_runs", "week_reference")
    op.drop_column("campaign_runs", "weekly_pack_id")
    op.drop_column("campaign_runs", "campaign_type")
