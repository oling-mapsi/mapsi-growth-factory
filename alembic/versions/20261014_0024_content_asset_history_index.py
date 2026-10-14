"""content asset history index

Revision ID: 20261014_0024
Revises: 20260725_0023
Create Date: 2026-10-14 11:40:00
"""

from alembic import op


revision = "20261014_0024"
down_revision = "20260725_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_content_assets_type_created_id",
        "content_assets",
        ["asset_type", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_assets_type_created_id", table_name="content_assets")
