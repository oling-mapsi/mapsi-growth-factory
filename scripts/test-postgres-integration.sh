#!/usr/bin/env bash
set -euo pipefail

export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://mapsi:mapsi@localhost:5433/mapsi_growth_factory_test}"

docker compose --profile test up -d postgres_test redis
alembic -x db_url="$TEST_DATABASE_URL" upgrade head
pytest -m postgres tests/integration/test_postgres_integration.py
