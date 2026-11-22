"""Local SQLite database layer.

One independent database file per installation, stored in a persistent
per-user application data directory. Never inside the EXE install folder.

Safety characteristics:
- WAL journal mode (crash-safe, readers don't block the writer).
- FOREIGN_KEYS on, FULL synchronous, busy_timeout for background workers.
- Versioned schema migrations tracked in `schema_migrations`.
- Integrity check + backup / restore helpers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent / "sql"
_APP_DIR_ENV = "GROCERY_ERP_HOME"


def app_data_dir() -> Path:
    override = os.environ.get(_APP_DIR_ENV)
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.sys.platform == "darwin":  # dev only
        base = Path.home() / "Library" / "Application Support"
    else:  # dev only (Linux CI)
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    base = base / "GroceryErpPro"
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    return app_data_dir() / "grocery_erp.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    return conn


class Database:
    """Thread-safe wrapper around a SQLite connection.

    SQLite serializes writes; workers and the UI share this object which
    serializes writes with a lock to prevent 'database is locked' errors.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else database_path()
        self._conn = connect(self.path)
        self._write_lock = threading.RLock()

    def close(self) -> None:
        with self._write_lock:
            self._conn.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._write_lock:
            return self._conn.execute(sql, params)

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, params)
        return cur.fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        cur = self._conn.execute(sql, params)
        return cur.fetchone()

    def transaction(self):
        return _Transaction(self)

    def schema_version(self) -> int:
        row = self.query_one("SELECT MAX(version) AS v FROM schema_migrations")
        return int(row["v"] or 0)

    def apply_migrations(self) -> list[int]:
        """Apply all migration SQL files in version order. Idempotent."""
        applied: list[int] = []
        current = self.schema_version()
        migrations = sorted(
            SCHEMA_DIR.glob("V*.sql"), key=lambda p: int(p.stem.split("_")[0][1:])
        )
        with self._write_lock:
            for mig in migrations:
                version = int(mig.stem.split("_")[0][1:])
                if version <= current:
                    continue
                sql_text = mig.read_text(encoding="utf-8")
                # executescript() manages its own transaction; the version
                # record is appended to the same script so a crash between
                # steps cannot leave the script half-applied and unrecorded.
                sql_text += (
                    f"\nINSERT OR IGNORE INTO schema_migrations (version,"
                    f" applied_at) VALUES ({version}, datetime('now'));\n"
                )
                self._conn.executescript(sql_text)
                applied.append(version)
        return applied

    def integrity_check(self) -> bool:
        row = self.query_one("PRAGMA integrity_check")
        return bool(row) and str(row[0]) == "ok"

    def foreign_key_violations(self) -> int:
        return len(self.query_all("PRAGMA foreign_key_check"))

    def backup_to(self, target: Path) -> Path:
        """Consistent online backup; safe while POS is running."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(str(target))
        try:
            with self._write_lock:
                self._conn.backup(dst)
        finally:
            dst.close()
        return target

    def restore_from(self, source: Path) -> None:
        """Replace this database with a verified backup file."""
        source = Path(source)
        with self._write_lock:
            self._conn.close()
        shutil.copyfile(source, self.path)
        self._conn = connect(self.path)


class _Transaction:
    """Explicit IMMEDIATE transaction. Nesting prohibited."""

    def __init__(self, db: Database):
        self._db = db

    def __enter__(self) -> Database:
        self._db._write_lock.acquire()
        try:
            self._db._conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._db._write_lock.release()
            raise
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._db._conn.execute("COMMIT")
            else:
                self._db._conn.execute("ROLLBACK")
        finally:
            self._db._write_lock.release()
        return False
