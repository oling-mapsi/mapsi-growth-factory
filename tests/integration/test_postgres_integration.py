import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL", "")


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_TEST_URL.startswith("postgresql+psycopg://"),
        reason="TEST_DATABASE_URL PostgreSQL non configuree.",
    ),
]


def test_audit_log_is_append_only_on_postgres() -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_TEST_URL)
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    command.upgrade(alembic_config, "head", sql=False, tag=None)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_logs"))
        connection.execute(text("DELETE FROM campaign_runs"))
        connection.execute(
            text(
                """
                INSERT INTO campaign_runs (id, name, objective, status, created_at, updated_at)
                VALUES ('c1', 'Campaign', 'Objective', 'DRAFT', now(), now())
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO audit_logs (id, campaign_run_id, event_type, payload, created_at)
                VALUES ('a1', 'c1', 'campaign.created', '{}'::json, now())
                """
            )
        )
    with engine.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE audit_logs SET event_type = 'mutated' WHERE id = 'a1'"))


def test_full_alembic_chain_creates_idempotency_table_on_postgres() -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_TEST_URL)
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    command.upgrade(alembic_config, "head", sql=False, tag=None)
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'idempotency_keys'
                """
            )
        ).scalar_one()

    assert result == "idempotency_keys"
