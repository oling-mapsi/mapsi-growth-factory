"""simple campaign workflow

Revision ID: 20260725_0023
Revises: 20260719_0022
Create Date: 2026-07-25 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260725_0023"
down_revision = "20260719_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaign_runs", sa.Column("theme", sa.Text(), nullable=False, server_default=""))
    op.add_column("campaign_runs", sa.Column("workflow_kind", sa.String(length=32), nullable=False, server_default="LEGACY"))
    op.add_column("campaign_runs", sa.Column("selected_channels", sa.JSON(), nullable=False, server_default="[]"))

    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("campaign_runs", "theme", server_default=None)
        op.alter_column("campaign_runs", "workflow_kind", server_default=None)
        op.alter_column("campaign_runs", "selected_channels", server_default=None)


def downgrade() -> None:
    op.drop_column("campaign_runs", "selected_channels")
    op.drop_column("campaign_runs", "workflow_kind")
    op.drop_column("campaign_runs", "theme")
