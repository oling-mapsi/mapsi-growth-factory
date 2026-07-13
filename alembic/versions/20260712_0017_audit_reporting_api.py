"""audit reporting api

Revision ID: 20260712_0017
Revises: 20260712_0016
Create Date: 2026-07-12 17:30:00.000000
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0017"
down_revision: Union[str, Sequence[str], None] = "20260712_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("content_asset_id", sa.String(length=36), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("actor_id", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("actor_source", sa.String(length=64), nullable=False, server_default="system"))
    op.add_column("audit_logs", sa.Column("actor_roles", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("audit_logs", sa.Column("correlation_id", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("idempotency_key", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("channel", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("result", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("source_ip", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("previous_state", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("audit_logs", sa.Column("new_state", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("audit_logs", sa.Column("previous_integrity_hash", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("audit_logs", sa.Column("integrity_hash", sa.String(length=64), nullable=False, server_default=""))
    op.alter_column("audit_logs", "campaign_run_id", existing_type=sa.String(length=36), nullable=True)

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id, campaign_run_id, content_asset_id, event_type, actor_id, actor_source, actor_roles,
                   correlation_id, idempotency_key, channel, result, source_ip, previous_state, new_state,
                   payload
            FROM audit_logs
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings()
    previous_hash = ""
    for row in rows:
        payload = {
            "campaign_run_id": row["campaign_run_id"] or "",
            "content_asset_id": row["content_asset_id"] or "",
            "event_type": row["event_type"] or "",
            "actor_id": row["actor_id"] or "",
            "actor_source": row["actor_source"] or "system",
            "actor_roles": row["actor_roles"] or [],
            "correlation_id": row["correlation_id"] or "",
            "idempotency_key": row["idempotency_key"] or "",
            "channel": row["channel"] or "",
            "result": row["result"] or "",
            "source_ip": row["source_ip"] or "",
            "previous_state": row["previous_state"] or {},
            "new_state": row["new_state"] or {},
            "payload": row["payload"] or {},
            "previous_integrity_hash": previous_hash,
        }
        computed = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
        conn.execute(
            sa.text(
                """
                UPDATE audit_logs
                SET previous_integrity_hash = :previous_integrity_hash,
                    integrity_hash = :integrity_hash
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "previous_integrity_hash": previous_hash,
                "integrity_hash": computed,
            },
        )
        previous_hash = computed


def downgrade() -> None:
    op.alter_column("audit_logs", "campaign_run_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_column("audit_logs", "integrity_hash")
    op.drop_column("audit_logs", "previous_integrity_hash")
    op.drop_column("audit_logs", "new_state")
    op.drop_column("audit_logs", "previous_state")
    op.drop_column("audit_logs", "source_ip")
    op.drop_column("audit_logs", "result")
    op.drop_column("audit_logs", "channel")
    op.drop_column("audit_logs", "idempotency_key")
    op.drop_column("audit_logs", "correlation_id")
    op.drop_column("audit_logs", "actor_roles")
    op.drop_column("audit_logs", "actor_source")
    op.drop_column("audit_logs", "actor_id")
    op.drop_column("audit_logs", "content_asset_id")
