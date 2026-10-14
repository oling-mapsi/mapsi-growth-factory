from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.core.db import Base
from app.infrastructure.db import models as _models  # noqa: F401


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def _clean(value):
    if isinstance(value, (datetime, date, Decimal, UUID)):
        return value
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, default=str))
    return value


def _chunks(rows: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def main() -> int:
    source_url = _env("SOURCE_DATABASE_URL")
    target_url = _env("TARGET_DATABASE_URL")
    if not target_url.startswith("mysql+pymysql://"):
        raise RuntimeError("TARGET_DATABASE_URL must use mysql+pymysql://")

    source = create_engine(source_url, future=True)
    target = create_engine(target_url, future=True)
    tables = [table for table in Base.metadata.sorted_tables if table.name != "alembic_version"]
    before: dict[str, int] = {}
    after: dict[str, int] = {}

    with source.connect() as source_conn, target.begin() as target_conn:
        for table in tables:
            before[table.name] = int(source_conn.execute(select(func.count()).select_from(table)).scalar_one())
            rows = [
                {column.name: _clean(row._mapping[column.name]) for column in table.columns}
                for row in source_conn.execute(select(table)).all()
            ]
            if not rows:
                after[table.name] = int(target_conn.execute(select(func.count()).select_from(table)).scalar_one())
                continue

            primary_keys = [column.name for column in table.primary_key.columns]
            update_columns = [column.name for column in table.columns if column.name not in primary_keys]
            for batch in _chunks(rows, 200):
                statement = mysql_insert(table).values(batch)
                if table.name == "audit_logs":
                    statement = statement.prefix_with("IGNORE")
                elif update_columns:
                    statement = statement.on_duplicate_key_update(
                        {name: statement.inserted[name] for name in update_columns}
                    )
                else:
                    statement = statement.prefix_with("IGNORE")
                target_conn.execute(statement)
            after[table.name] = int(target_conn.execute(select(func.count()).select_from(table)).scalar_one())

    print("table,source_count,target_count")
    for table in tables:
        print(f"{table.name},{before[table.name]},{after[table.name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
