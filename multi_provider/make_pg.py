"""Copies shop.db (SQLite) into Postgres so you can practice the same agent on Postgres.

Prereq:  docker run -d --name pg -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:17
         pip install "psycopg[binary]"
Run:     python make_db.py   (if shop.db is missing)
         python multi_provider/make_pg.py   (drops and recreates the 4 tables every time)

Same traps as shop.db (mixed-case status, trailing spaces, NULLs, paise),
plus Postgres-specific ones: order_date / signup_date are real DATE columns.
"""
import os
import sqlite3

import psycopg

PG_URL = os.environ.get("PG_URL", "postgresql://postgres:pg@localhost:5432/postgres")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # project folder (one level up)

SCHEMA = """
DROP TABLE IF EXISTS refunds, order_items, orders, products, customers;

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    city        TEXT,
    signup_date DATE NOT NULL
);
CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price_paise INTEGER
);
CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date  DATE NOT NULL,
    status      TEXT NOT NULL
);
CREATE TABLE order_items (
    id               INTEGER PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES orders(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    quantity         INTEGER NOT NULL,
    unit_price_paise INTEGER NOT NULL
);
"""

TABLES = {
    "customers": "id, name, email, city, signup_date",
    "products": "id, name, category, price_paise",
    "orders": "id, customer_id, order_date, status",
    "order_items": "id, order_id, product_id, quantity, unit_price_paise",
}


def main():
    src = sqlite3.connect(os.path.join(HERE, "shop.db"))
    with psycopg.connect(PG_URL) as pg:
        pg.execute(SCHEMA)
        for table, cols in TABLES.items():
            rows = src.execute(f"SELECT {cols} FROM {table}").fetchall()
            placeholders = ", ".join(["%s"] * len(cols.split(",")))
            with pg.cursor() as cur:
                cur.executemany(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", rows)
            print(f"  {table:<12} {len(rows)} rows")
    print(f"Loaded into {PG_URL}")


if __name__ == "__main__":
    main()
