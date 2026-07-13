"""channel operational state

Revision ID: 20260712_0016
Revises: 20260712_0015
Create Date: 2026-07-12 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0016"
down_revision: str | Sequence[str] | None = "20260712_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_operational_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("feature_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("feature_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emergency_kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", name="uq_channel_operational_states_channel"),
    )
    op.create_table(
        "global_operational_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("global_kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "channel_operational_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("channel_operational_audits")
    op.drop_table("global_operational_states")
    op.drop_table("channel_operational_states")
