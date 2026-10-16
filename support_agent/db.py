"""
db.py - SQLite connection, query helpers with a timeout, and this app's schema.

Tools never touch sqlite3 directly for reads; they call query()/query_one().
That gives one place to add the timeout, row conversion and (later) logging.
"""

import os
import shutil
import sqlite3
import time

from . import config

if not os.path.exists(config.DB_PATH):
    # Work on a copy: refunds WRITE to the database, and the seed data that
    # other exercises depend on must never change. Reset with: del support.db
    shutil.copy(config.SEED_DB_PATH, config.DB_PATH)

conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row      # rows behave like dicts: row["status"], dict(row)

# The refunds table belongs to THIS app.
#   UNIQUE(order_id)        at most one refund per order, enforced by the database.
#                           Last line of defence for idempotency: even if two
#                           identical requests race, the second INSERT fails.
#   CHECK(amount_paise > 0) the database itself rejects zero/negative refunds.
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS refunds (
        id           INTEGER PRIMARY KEY,
        order_id     INTEGER NOT NULL UNIQUE REFERENCES orders(id),
        amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
        created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
)
conn.commit()

# Re-exported so other modules catch DB errors without importing sqlite3.
IntegrityError = sqlite3.IntegrityError
OperationalError = sqlite3.OperationalError


def query(sql, params=()):
    """Run a read query with a wall-clock timeout. Returns a list of plain dicts.

    SQLite has no statement_timeout, so we install a progress handler: SQLite
    calls it every 10k VM steps, and a non-zero return aborts the statement
    with OperationalError('interrupted'). The dispatcher turns that into a
    clean JSON error instead of a hung agent.
    """
    deadline = time.monotonic() + config.QUERY_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.set_progress_handler(None, 0)


def query_one(sql, params=()):
    """One dict or None. Callers MUST handle None ("not found" is a real case)."""
    rows = query(sql, params)
    return rows[0] if rows else None
