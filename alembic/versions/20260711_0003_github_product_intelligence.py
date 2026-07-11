"""github product intelligence

Revision ID: 20260711_0003
Revises: 20260711_0002
Create Date: 2026-07-11 19:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_evidences") as batch_op:
        batch_op.alter_column("campaign_run_id", existing_type=sa.String(length=36), nullable=True)
    op.create_table(
        "repository_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("full_name", name="uq_repository_sources_full_name"),
    )
    op.create_table(
        "repository_cursors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("repository_source_id", sa.String(length=36), sa.ForeignKey("repository_sources.id"), nullable=False),
        sa.Column("cursor_type", sa.String(length=64), nullable=False),
        sa.Column("last_seen_sha", sa.String(length=64), nullable=False),
        sa.Column("last_delivery_id", sa.String(length=255), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_source_id", "cursor_type", name="uq_repository_cursors_source_type"),
    )
    op.create_table(
        "product_changes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("repository_source_id", sa.String(length=36), sa.ForeignKey("repository_sources.id"), nullable=False),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("issue_numbers", sa.JSON(), nullable=False),
        sa.Column("release_tag", sa.String(length=255), nullable=False),
        sa.Column("deployment_ref", sa.String(length=255), nullable=False),
        sa.Column("production_status", sa.String(length=64), nullable=False),
        sa.Column("change_note_path", sa.String(length=255), nullable=False),
        sa.Column("eligible_for_communication", sa.Boolean(), nullable=False),
        sa.Column("confidential", sa.Boolean(), nullable=False),
        sa.Column("target_client_key", sa.String(length=255), nullable=False),
        sa.Column("capability_key", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("deployment_proven", sa.Boolean(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("repository_source_id", "sha", "change_note_path", name="uq_product_changes_source_sha_note"),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("delivery_id", name="uq_webhook_deliveries_delivery_id"),
    )
    with op.batch_alter_table("source_evidences") as batch_op:
        batch_op.add_column(sa.Column("product_change_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("evidence_type", sa.String(length=64), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.create_foreign_key("fk_source_evidences_product_change_id", "product_changes", ["product_change_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("source_evidences") as batch_op:
        batch_op.drop_constraint("fk_source_evidences_product_change_id", type_="foreignkey")
        batch_op.drop_column("payload")
        batch_op.drop_column("evidence_type")
        batch_op.drop_column("product_change_id")
        batch_op.alter_column("campaign_run_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_table("webhook_deliveries")
    op.drop_table("product_changes")
    op.drop_table("repository_cursors")
    op.drop_table("repository_sources")
