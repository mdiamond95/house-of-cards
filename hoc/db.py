"""SQLite access for hoc.db. No ORM — plain sqlite3 with foreign keys on."""

import sqlite3
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PACKAGE_ROOT / "schema.sql"
DEFAULT_DB_PATH = PACKAGE_ROOT.parent / "hoc.db"

__all__ = ["connect", "init_schema", "query", "one", "SCHEMA_PATH", "DEFAULT_DB_PATH"]


def connect(path=DEFAULT_DB_PATH):
    """Open a connection with foreign keys enforced and rows as sqlite3.Row.

    Foreign keys are off by default in SQLite and are a per-connection setting,
    so every connection must switch them on — the schema's own PRAGMA line only
    applies while the schema script runs.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    """Create the schema in an empty database."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # executescript commits and can reset pragmas; re-assert foreign keys.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(conn, sql, params=()):
    """Run a SELECT and return all rows."""
    return conn.execute(sql, params).fetchall()


def one(conn, sql, params=()):
    """Run a SELECT expected to yield a single value; return it (or None)."""
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]
