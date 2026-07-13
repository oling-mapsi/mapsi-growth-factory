"""editorial source packs

Revision ID: 20260713_0020
Revises: 20260713_0019
Create Date: 2026-07-13 13:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0020"
down_revision = "20260713_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_source_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("weekly_pack_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("campaign_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("confidentiality_level", sa.String(length=32), nullable=False, server_default="INTERNAL"),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "editorial_source_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_pack_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source_title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_author", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("factual_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("usable_facts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("anonymized_facts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("prohibited_facts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("client_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("client_name_usage_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidentiality_level", sa.String(length=32), nullable=False, server_default="INTERNAL"),
        sa.Column("evidence_quality", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("source_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("external_source_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("manual_input", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_pack_id"], ["editorial_source_packs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "editorial_source_attachment_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_item_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("media_type", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("storage_reference", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_item_id"], ["editorial_source_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if op.get_bind().dialect.name != "sqlite":
        for table, columns in (
            ("editorial_source_packs", ("weekly_pack_id", "summary", "status", "confidentiality_level", "created_by", "validated_by")),
            (
                "editorial_source_items",
                (
                    "source_reference",
                    "source_title",
                    "source_author",
                    "factual_summary",
                    "usable_facts",
                    "anonymized_facts",
                    "prohibited_facts",
                    "client_name",
                    "client_name_usage_authorized",
                    "confidentiality_level",
                    "evidence_quality",
                    "source_url",
                    "external_source_id",
                    "content_hash",
                    "manual_input",
                ),
            ),
            ("editorial_source_attachment_references", ("file_name", "media_type", "storage_reference", "source_url", "content_hash")),
        ):
            for column in columns:
                op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    op.drop_table("editorial_source_attachment_references")
    op.drop_table("editorial_source_items")
    op.drop_table("editorial_source_packs")
