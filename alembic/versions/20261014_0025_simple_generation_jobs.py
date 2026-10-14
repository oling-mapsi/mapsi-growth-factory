"""simple generation jobs

Revision ID: 20261014_0025
Revises: 20261014_0024
Create Date: 2026-10-14 13:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_0025"
down_revision = "20261014_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simple_generation_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simple_generation_jobs_status_updated", "simple_generation_jobs", ["status", "updated_at"], unique=False)
    op.create_index("ix_simple_generation_jobs_campaign_status", "simple_generation_jobs", ["campaign_run_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_simple_generation_jobs_campaign_status", table_name="simple_generation_jobs")
    op.drop_index("ix_simple_generation_jobs_status_updated", table_name="simple_generation_jobs")
    op.drop_table("simple_generation_jobs")
