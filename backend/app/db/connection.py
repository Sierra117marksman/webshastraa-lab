"""SQLite connection, transaction, and WAL-safe backup primitives for AI Employee."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "ai_employee.db"
DB_PATH = os.getenv("AI_EMPLOYEE_DB_PATH", str(DEFAULT_DB_PATH))


class DatabaseError(RuntimeError):
    """Base error for database infrastructure failures."""


class MigrationError(DatabaseError):
    """Raised when a database migration cannot complete safely."""


def get_connection(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Each connection independently enables foreign keys and WAL-mode settings.
    """
    path = str(db_path or DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(
    db_path: str | os.PathLike[str] | None = None,
) -> Iterator[sqlite3.Connection]:
    """Run a multi-record mutation in one atomic SQLite transaction."""
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wal_safe_backup(
    src_path: str | os.PathLike[str],
    backup_path: str | os.PathLike[str],
) -> None:
    """Create a consistent SQLite backup using the native online backup API.

    A plain filesystem copy is deliberately avoided because a WAL-mode database
    may contain committed frames outside the main .db file.
    """
    src = Path(src_path)
    dst = Path(backup_path)
    if not src.exists():
        raise FileNotFoundError(src)

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()

    src_conn = sqlite3.connect(str(src), timeout=30.0)
    dst_conn = sqlite3.connect(str(dst), timeout=30.0)
    try:
        src_conn.execute("PRAGMA busy_timeout = 30000")
        src_conn.execute("PRAGMA journal_mode = WAL")
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src_conn.backup(dst_conn, pages=0)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()
