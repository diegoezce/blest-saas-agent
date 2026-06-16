"""Shared pytest setup.

The ORM models use Postgres JSONB columns. Tests run on in-memory SQLite, which
can't render JSONB DDL, so register a compiler that maps JSONB → JSON for SQLite.
This makes Base.metadata.create_all() work for DB-backed tests without a real Postgres.
"""
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - DDL shim
    return "JSON"
