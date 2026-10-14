import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

MYSQL_TEST_URL = os.getenv("TEST_DATABASE_URL", "")


pytestmark = [
    pytest.mark.mysql,
    pytest.mark.skipif(
        not MYSQL_TEST_URL.startswith("mysql+pymysql://"),
        reason="TEST_DATABASE_URL MySQL non configuree.",
    ),
]


def test_mysql_alembic_chain_and_audit_append_only() -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", MYSQL_TEST_URL)
    engine = create_engine(MYSQL_TEST_URL, future=True)
    command.upgrade(alembic_config, "head", sql=False, tag=None)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_logs"))
        connection.execute(text("DELETE FROM campaign_runs"))
        connection.execute(
            text(
                """
                INSERT INTO campaign_runs (
                    id, name, objective, status, created_at, updated_at,
                    campaign_type, weekly_pack_id, week_reference, week_year, week_number, pilot_mode,
                    theme, workflow_kind, selected_channels
                )
                VALUES (
                    'c1', 'Campaign', 'Objective', 'DRAFT', now(), now(),
                    'OLING', '', '', 0, 0, false,
                    'Theme', 'SIMPLE', JSON_ARRAY()
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO audit_logs (
                    id, campaign_run_id, event_type, payload, created_at,
                    content_asset_id, actor_id, actor_source, actor_roles,
                    correlation_id, idempotency_key, channel, result, source_ip,
                    previous_state, new_state, previous_integrity_hash, integrity_hash
                )
                VALUES (
                    'a1', 'c1', 'campaign.created', JSON_OBJECT(), now(),
                    '', 'tester', 'test', JSON_ARRAY(),
                    'corr-1', '', '', 'success', '',
                    JSON_OBJECT(), JSON_OBJECT(), '', ''
                )
                """
            )
        )
    with engine.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE audit_logs SET event_type = 'mutated' WHERE id = 'a1'"))
        result = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = 'idempotency_keys'
                """
            )
        ).scalar_one()

    assert result == "idempotency_keys"
