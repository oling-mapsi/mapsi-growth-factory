"""mapsi usage collector

Revision ID: 20260711_0004
Revises: 20260711_0003
Create Date: 2026-07-11 20:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0004"
down_revision = "20260711_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapsi_instances",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("instance_key", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("instance_key", name="uq_mapsi_instances_instance_key"),
    )
    op.create_table(
        "customer_accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mapsi_instance_id", sa.String(length=36), sa.ForeignKey("mapsi_instances.id"), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mapsi_instance_id", "external_account_id", name="uq_customer_accounts_instance_external"),
    )
    op.create_table(
        "contact_identities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email_hash", name="uq_contact_identities_email_hash"),
    )
    op.create_table(
        "contact_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("contact_identity_id", sa.String(length=36), sa.ForeignKey("contact_identities.id"), nullable=False),
        sa.Column("customer_account_id", sa.String(length=36), sa.ForeignKey("customer_accounts.id"), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("communication_eligible", sa.Boolean(), nullable=False),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "contact_identity_id",
            "customer_account_id",
            "external_user_id",
            name="uq_contact_memberships_identity_account_user",
        ),
    )
    op.create_table(
        "usage_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mapsi_instance_id", sa.String(length=36), sa.ForeignKey("mapsi_instances.id"), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=64), nullable=False),
        sa.Column("source_cursor", sa.String(length=255), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("mapsi_instance_id", "snapshot_kind", "source_cursor", name="uq_usage_snapshots_instance_kind_cursor"),
    )
    op.create_table(
        "feature_adoptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("usage_snapshot_id", sa.String(length=36), sa.ForeignKey("usage_snapshots.id"), nullable=False),
        sa.Column("contact_membership_id", sa.String(length=36), sa.ForeignKey("contact_memberships.id"), nullable=False),
        sa.Column("module_key", sa.String(length=128), nullable=False),
        sa.Column("events_last_7_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "usage_snapshot_id",
            "contact_membership_id",
            "module_key",
            name="uq_feature_adoptions_snapshot_membership_module",
        ),
    )
    op.create_table(
        "instance_capabilities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mapsi_instance_id", sa.String(length=36), sa.ForeignKey("mapsi_instances.id"), nullable=False),
        sa.Column("capability_key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mapsi_instance_id", "capability_key", name="uq_instance_capabilities_instance_key"),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mapsi_instance_id", sa.String(length=36), sa.ForeignKey("mapsi_instances.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_usage_cursor", sa.String(length=255), nullable=False),
        sa.Column("last_contact_cursor", sa.String(length=255), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("collection_runs")
    op.drop_table("instance_capabilities")
    op.drop_table("feature_adoptions")
    op.drop_table("usage_snapshots")
    op.drop_table("contact_memberships")
    op.drop_table("contact_identities")
    op.drop_table("customer_accounts")
    op.drop_table("mapsi_instances")
