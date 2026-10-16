"""
================================================================================
 db_sqlite.py  -  SQLite adapter for the support tools
================================================================================

 Why an adapter?
   The tool handlers (support_tools.py) must not care which database they run
   on. Both adapters (this file and db_postgres.py) expose the SAME small
   interface, so the handlers are written once:

     dialect            "sqlite" | "postgres"
     for_update         SQL suffix that row-locks inside a transaction ("" here)
     query(sql, params) -> list[dict]       read, with a timeout
     query_one(...)     -> dict | None      caller MUST handle None
     transaction()      context manager: all-or-nothing writes
     Error / IntegrityError / OperationalError   exception classes to catch

   SQL in the handlers uses "?" placeholders. The Postgres adapter translates
   them to "%s". (Only safe because the SQL text is OURS - the model never
   writes SQL in this agent; it only supplies parameter VALUES.)

 Data file: support.db (copied from shop.db on first use, so writes such as
 refunds never touch the seed data). Reset with:  del support.db
================================================================================
"""

import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "support.db")
SEED_PATH = os.path.join(HERE, "shop.db")

REFUNDS_DDL = """
CREATE TABLE IF NOT EXISTS refunds (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL UNIQUE REFERENCES orders(id),   -- one refund per order
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class SQLiteDB:
    dialect = "sqlite"
    for_update = ""      # SQLite locks the whole DB with BEGIN IMMEDIATE instead of rows

    Error = sqlite3.Error
    IntegrityError = sqlite3.IntegrityError
    OperationalError = sqlite3.OperationalError

    def __init__(self, path=DEFAULT_PATH, timeout_seconds=5.0):
        if not os.path.exists(path):
            shutil.copy(SEED_PATH, path)
        # isolation_level=None -> autocommit mode. We start transactions
        # ourselves (BEGIN IMMEDIATE) so a read-check-then-write sequence is
        # atomic and no other writer can sneak in between the check and the write.
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")   # SQLite ignores FKs unless asked
        self.conn.execute(REFUNDS_DDL)
        self.timeout_seconds = timeout_seconds
        self.path = path

    # ── reads ────────────────────────────────────────────────────────────────

    def query(self, sql, params=()):
        """Run SQL with a wall-clock timeout; return rows as plain dicts.

        SQLite has no statement_timeout, so a progress handler (called every
        10k VM steps) aborts the statement once the deadline passes. The abort
        surfaces as OperationalError('interrupted'), which the dispatcher turns
        into a JSON error instead of a hung agent.
        """
        deadline = time.monotonic() + self.timeout_seconds
        self.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cur = self.conn.execute(sql, self._adapt(params))
            return [dict(r) for r in cur.fetchall()]
        finally:
            self.conn.set_progress_handler(None, 0)

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ── writes ───────────────────────────────────────────────────────────────

    @contextmanager
    def transaction(self):
        """All-or-nothing block: COMMIT on success, ROLLBACK on any exception."""
        self.conn.execute("BEGIN IMMEDIATE")   # take the write lock up front
        try:
            yield self
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _adapt(params):
        # Handlers pass datetime.date objects (they validate dates properly).
        # SQLite stores dates as ISO text, and Python 3.12+ deprecates the
        # implicit date adapter, so convert explicitly.
        return tuple(p.isoformat() if isinstance(p, (date, datetime)) else p for p in params)
