"""Builds shop.db: a small e-commerce database for tool-layer practice.

Run:  python make_db.py      (deletes and recreates shop.db every time)

Deliberately realistic mess (these are the traps your tools must handle):
  - customer names with mixed case / stray spaces    -> exact '=' matches fail
  - some emails and cities are NULL                  -> NULL is not '' and not = NULL
  - money is stored in PAISE (integer), not rupees   -> 49900 means Rs 499.00
  - order status has mixed case ('delivered' vs 'Delivered')
  - a customer with zero orders                      -> INNER JOIN silently drops them
  - a product with NULL price (discontinued)
  - ~600 orders                                      -> SELECT * without LIMIT floods the context
"""
import os
import random
import sqlite3
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.db")

SCHEMA = """
CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,                 -- nullable
    city        TEXT,                 -- nullable
    signup_date TEXT NOT NULL         -- ISO 'YYYY-MM-DD'
);

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price_paise INTEGER               -- price in paise; NULL = discontinued
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date  TEXT NOT NULL,        -- ISO 'YYYY-MM-DD'
    status      TEXT NOT NULL         -- delivered / shipped / cancelled / refunded (case is inconsistent!)
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price_paise INTEGER NOT NULL -- price at time of purchase
);
"""

CUSTOMERS = [
    # (name, email, city)
    ("Asha Rao",        "asha.rao@example.com",    "Bengaluru"),
    ("John Doe",        "john.doe@example.com",    "Mumbai"),
    ("Jane Smith",      None,                      "Delhi"),
    ("vikram shah",     "vikram@example.com",      "Pune"),        # lowercase
    ("Priya  Nair",     "priya.nair@example.com",  "Kochi"),       # double space
    ("Rahul Verma ",    "rahul.v@example.com",     None),          # trailing space, NULL city
    ("Meera Iyer",      "meera@example.com",       "Chennai"),
    ("ARJUN MEHTA",     "arjun.m@example.com",     "Ahmedabad"),   # uppercase
    ("Sneha Kulkarni",  None,                      "Pune"),
    ("Karan Malhotra",  "karan@example.com",       "Delhi"),
    ("Fatima Sheikh",   "fatima@example.com",      "Hyderabad"),
    ("Rohan Gupta",     "rohan.g@example.com",     "Mumbai"),
    ("Ananya Das",      "ananya@example.com",      "Kolkata"),
    ("Siddharth Jain",  "sid.jain@example.com",    "Jaipur"),
    ("Neha Reddy",      "neha.r@example.com",      "Hyderabad"),
    ("Aditya Kumar",    "aditya.k@example.com",    "Bengaluru"),
    ("Pooja Singh",     None,                      None),
    ("Imran Khan",      "imran@example.com",       "Lucknow"),
    ("Divya Menon",     "divya@example.com",       "Kochi"),
    ("Zoya Ali",        "zoya@example.com",        "Delhi"),       # will have ZERO orders
]
ZERO_ORDER_CUSTOMER = "Zoya Ali"

PRODUCTS = [
    # (name, category, price_paise)
    ("Wireless Mouse",       "Electronics", 79900),
    ("Mechanical Keyboard",  "Electronics", 349900),
    ("USB-C Cable",          "Electronics", 29900),
    ("Noise-Cancelling Headphones", "Electronics", 899900),
    ("Cotton T-Shirt",       "Apparel",     49900),
    ("Running Shoes",        "Apparel",     299900),
    ("Denim Jacket",         "Apparel",     249900),
    ("Coffee Mug",           "Home",        34900),
    ("Desk Lamp",            "Home",        129900),
    ("Yoga Mat",             "Fitness",     89900),
    ("Steel Water Bottle",   "Fitness",     59900),
    ("Old MP3 Player",       "Electronics", None),          # discontinued, NULL price
]

STATUSES = ["delivered"] * 6 + ["Delivered"] * 2 + ["shipped", "SHIPPED"] + ["cancelled"] * 2 + ["refunded"]


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    rng = random.Random(42)  # fixed seed -> same data every run
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    start = date(2025, 1, 1)
    for name, email, city in CUSTOMERS:
        signup = start + timedelta(days=rng.randint(0, 200))
        con.execute(
            "INSERT INTO customers (name, email, city, signup_date) VALUES (?, ?, ?, ?)",
            (name, email, city, signup.isoformat()),
        )
    con.executemany(
        "INSERT INTO products (name, category, price_paise) VALUES (?, ?, ?)", PRODUCTS
    )

    customer_ids = [
        row[0]
        for row in con.execute("SELECT id FROM customers WHERE name != ?", (ZERO_ORDER_CUSTOMER,))
    ]
    sellable = [(pid, price) for pid, price in con.execute(
        "SELECT id, price_paise FROM products WHERE price_paise IS NOT NULL")]

    # Asha Rao is weighted heavier so "top customer" questions have a clear answer.
    weights = [5 if cid == 1 else 1 for cid in customer_ids]

    for _ in range(600):
        cid = rng.choices(customer_ids, weights=weights)[0]
        odate = date(2025, 3, 1) + timedelta(days=rng.randint(0, 540))
        status = rng.choice(STATUSES)
        cur = con.execute(
            "INSERT INTO orders (customer_id, order_date, status) VALUES (?, ?, ?)",
            (cid, odate.isoformat(), status),
        )
        oid = cur.lastrowid
        for pid, price in rng.sample(sellable, rng.randint(1, 3)):
            con.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price_paise) "
                "VALUES (?, ?, ?, ?)",
                (oid, pid, rng.randint(1, 4), price),
            )

    con.commit()

    print(f"Created {DB_PATH}")
    for table in ("customers", "products", "orders", "order_items"):
        (n,) = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        print(f"  {table:<12} {n} rows")
    con.close()


if __name__ == "__main__":
    build()
