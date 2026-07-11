"""initial schema

Revision ID: 20260711_0001
Revises:
Create Date: 2026-07-11 16:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "editorial_briefs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "content_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audience_segments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "publications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "interactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("interaction_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_evidences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_run_id", sa.String(length=36), sa.ForeignKey("campaign_runs.id"), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("method", "path", "idempotency_key", name="uq_idempotency_method_path_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("audit_logs")
    op.drop_table("source_evidences")
    op.drop_table("leads")
    op.drop_table("interactions")
    op.drop_table("publications")
    op.drop_table("approval_decisions")
    op.drop_table("audience_segments")
    op.drop_table("content_assets")
    op.drop_table("editorial_briefs")
    op.drop_table("campaign_runs")
