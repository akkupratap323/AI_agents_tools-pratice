"""
================================================================================
 db_postgres.py  -  PostgreSQL adapter for the support tools
================================================================================

 Same interface as db_sqlite.py (see that file for the contract).

 Setup (once):
   docker run -d --name pg -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:17
   pip install "psycopg[binary]"
   python make_pg.py                      # loads shop.db's data into Postgres
 Connection string: env PG_URL, default postgresql://postgres:pg@localhost:5432/postgres

 ------------------------------------------------------------------------------
 POSTGRES GOTCHAS THIS ADAPTER HANDLES (classic tool-layer bugs)
 ------------------------------------------------------------------------------
 1. ABORTED TRANSACTION POISONING
    Without autocommit, one failed statement puts the connection in an
    "aborted transaction" state and EVERY later query fails with
    "current transaction is aborted, commands ignored until end of transaction
    block". One bad call would break every later tool call.
    -> autocommit=True; explicit transactions only via transaction(), which
       always commits or rolls back.

 2. Decimal / date / datetime ARE NOT JSON-SERIALIZABLE
    Postgres returns NUMERIC as decimal.Decimal and DATE as datetime.date.
    json.dumps() then raises TypeError *after* the query succeeded.
    -> _normalize() converts them to float / ISO strings at the boundary.

 3. NO TIMEOUT BY DEFAULT
    A runaway query blocks the agent forever.
    -> SET statement_timeout; the error (QueryCanceled) is an OperationalError
       and becomes a clean JSON error.

 4. PLACEHOLDERS ARE %s, NOT ?
    -> _sql() translates. psycopg also treats a literal % in SQL text as a
       placeholder marker; our SQL never contains one (LIKE patterns are
       passed as parameter VALUES, e.g. '%asha%').

 5. RACES ON WRITES
    Two identical refund requests can both pass the "already refunded?" check.
    -> transaction() + SELECT ... FOR UPDATE (self.for_update) locks the order
       row, and UNIQUE(order_id) on refunds is the final guarantee.

 Least privilege (production): the agent's DB user should only have SELECT on
 the read tables and INSERT on refunds / UPDATE(status) on orders - never DDL.
================================================================================
"""

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

DEFAULT_URL = os.environ.get("PG_URL", "postgresql://postgres:pg@localhost:5432/postgres")

REFUNDS_DDL = """
CREATE TABLE IF NOT EXISTS refunds (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id     INTEGER NOT NULL UNIQUE REFERENCES orders(id),   -- one refund per order
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class PostgresDB:
    dialect = "postgres"
    for_update = " FOR UPDATE"   # row lock, held until the transaction ends

    Error = psycopg.Error
    IntegrityError = psycopg.IntegrityError          # includes UniqueViolation
    OperationalError = psycopg.OperationalError      # includes QueryCanceled (timeout)

    def __init__(self, url=DEFAULT_URL, timeout_seconds=5.0):
        self.conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)   # gotcha 1
        self.conn.execute(f"SET statement_timeout = '{int(timeout_seconds * 1000)}ms'")  # gotcha 3
        self.conn.execute(REFUNDS_DDL)
        self.path = url.rsplit("@", 1)[-1]   # for logging, without the password

    def query(self, sql, params=()):
        rows = self.conn.execute(self._sql(sql), params).fetchall() if self._returns_rows(sql) \
            else self._exec_no_rows(sql, params)
        return [self._normalize(r) for r in rows]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self):
        # psycopg's transaction() commits on success, rolls back on exception.
        with self.conn.transaction():
            yield self

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _sql(sql):
        return sql.replace("?", "%s")                                         # gotcha 4

    @staticmethod
    def _returns_rows(sql):
        s = sql.lstrip().upper()
        return s.startswith(("SELECT", "WITH")) or " RETURNING " in f" {s} "

    def _exec_no_rows(self, sql, params):
        self.conn.execute(self._sql(sql), params)
        return []

    @staticmethod
    def _normalize(row):                                                      # gotcha 2
        out = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            out[key] = value
        return out
