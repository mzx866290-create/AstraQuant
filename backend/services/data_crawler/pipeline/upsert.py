"""Dialect-aware insert helpers for crawler ETL pipelines."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import insert as generic_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def session_dialect_name(db_session) -> str:
    bind = db_session.get_bind() if hasattr(db_session, "get_bind") else getattr(db_session, "bind", None)
    return getattr(getattr(bind, "dialect", None), "name", "")


def insert_do_nothing(model, values: dict, conflict_columns: Sequence[str], dialect_name: str):
    columns = list(conflict_columns)
    if dialect_name == "postgresql":
        return postgres_insert(model).values(**values).on_conflict_do_nothing(index_elements=columns)
    if dialect_name == "sqlite":
        return sqlite_insert(model).values(**values).on_conflict_do_nothing(index_elements=columns)
    return generic_insert(model).values(**values)
