"""mautic contact sync

Revision ID: 20260711_0006
Revises: 20260711_0005
Create Date: 2026-07-11 22:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0006"
down_revision = "20260711_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contact_identities", sa.Column("encrypted_email", sa.Text(), nullable=False, server_default=""))
    op.add_column("contact_identities", sa.Column("email_valid", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "mautic_contact_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("contact_identity_id", sa.String(length=36), sa.ForeignKey("contact_identities.id"), nullable=False),
        sa.Column("mautic_contact_id", sa.String(length=64), nullable=False),
        sa.Column("email_hash", sa.String(length=128), nullable=False),
        sa.Column("dnc_applied", sa.Boolean(), nullable=False),
        sa.Column("remote_unsubscribed", sa.Boolean(), nullable=False),
        sa.Column("last_sync_status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contact_identity_id", name="uq_mautic_contact_links_identity"),
        sa.UniqueConstraint("mautic_contact_id", name="uq_mautic_contact_links_mautic_id"),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("contact_identities", "encrypted_email", server_default=None)
        op.alter_column("contact_identities", "email_valid", server_default=None)


def downgrade() -> None:
    op.drop_table("mautic_contact_links")
    op.drop_column("contact_identities", "email_valid")
    op.drop_column("contact_identities", "encrypted_email")
