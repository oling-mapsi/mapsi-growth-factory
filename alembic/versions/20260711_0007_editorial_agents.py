"""editorial agents

Revision ID: 20260711_0007
Revises: 20260711_0006
Create Date: 2026-07-11 23:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0007"
down_revision = "20260711_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_theme_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.String(length=64), nullable=False),
        sa.Column("audience_segment_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_execution_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_name", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("execution_params", sa.JSON(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_execution_logs")
    op.drop_table("editorial_theme_history")
