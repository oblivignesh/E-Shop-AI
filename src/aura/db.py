"""Read-only SQLAlchemy engine + reflected table access for AURA.

Provides a shared engine, a small helper for parametrized queries, and cached
Table objects reflected from data/aura.db so tools can reference columns
symbolically without string-concatenating SQL.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.engine import Engine

from aura.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(settings.db_url, future=True)


@lru_cache(maxsize=1)
def get_metadata() -> MetaData:
    md = MetaData()
    md.reflect(bind=get_engine())
    return md


def get_table(name: str) -> Table:
    md = get_metadata()
    if name not in md.tables:
        raise KeyError(
            f"Table '{name}' not found in {settings.db_path}. "
            "Have you run `python scripts/ingest.py`?"
        )
    return md.tables[name]


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict[str, Any] | None = None) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount or 0
