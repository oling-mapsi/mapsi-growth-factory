"""studio admin authentication

Revision ID: 20260712_0015
Revises: 20260712_0014
Create Date: 2026-07-12 13:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_0015"
down_revision = "20260712_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_admin_jti_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("jti", sa.String(length=255), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("audience", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("key_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_studio_admin_jti_records_jti"),
    )
    op.create_table(
        "studio_admin_access_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_roles", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("actor_permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="mapsi-studio"),
        sa.Column("jti", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source_ip", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="GET"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    if op.get_bind().dialect.name != "sqlite":
        for table, column in (
            ("studio_admin_jti_records", "key_id"),
            ("studio_admin_access_audits", "actor_roles"),
            ("studio_admin_access_audits", "actor_permissions"),
            ("studio_admin_access_audits", "source"),
            ("studio_admin_access_audits", "correlation_id"),
            ("studio_admin_access_audits", "source_ip"),
            ("studio_admin_access_audits", "path"),
            ("studio_admin_access_audits", "method"),
        ):
            op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    op.drop_table("studio_admin_access_audits")
    op.drop_table("studio_admin_jti_records")
