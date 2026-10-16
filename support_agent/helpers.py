"""
helpers.py - small functions shared by several tools.

Validation helpers raise ToolError with a hint, so every tool rejects bad input
the same way. Lookup helpers encode "not found is an error" once.
"""

from datetime import date

from .db import query_one
from .errors import ToolError


# ── validation ───────────────────────────────────────────────────────────────

def normalize_name(name):
    """'  priya   NAIR ' -> 'priya nair'  (collapse all whitespace, lowercase)."""
    return " ".join(str(name).split()).lower()


def clean_display(name):
    """'Priya  Nair ' -> 'Priya Nair'  (tidy for output, keep the case)."""
    return " ".join(str(name).split())


def positive_int(value, field):
    # bool is a subclass of int in Python (True == 1), so reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("invalid_argument", f"{field} must be a positive integer, got {value!r}.",
                        hint=f"Pass {field} as a number like 42.")
    return value


def parse_date(value, field):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError("invalid_date", f"{field} must be YYYY-MM-DD, got {value!r}.",
                        hint="Convert the user's period to ISO dates, e.g. January 2026 -> "
                             "start_date 2026-01-01, end_date 2026-01-31.")


# ── formatting ───────────────────────────────────────────────────────────────

def rupees(paise):
    """Paise (integer, how money is stored) -> rupees (float, how humans read it)."""
    return round((paise or 0) / 100, 2)


# ── shared lookups ───────────────────────────────────────────────────────────

def require_order(order_id):
    """Return the order (status normalised) or raise order_not_found."""
    order = query_one(
        "SELECT id, customer_id, order_date, LOWER(TRIM(status)) AS status FROM orders WHERE id = ?",
        (order_id,),
    )
    if order is None:
        raise ToolError("order_not_found", f"No order with id {order_id}.",
                        hint="Check the id with the user, or list their orders with get_customer_orders.")
    return order


def order_total_paise(order_id):
    # COALESCE: an order with no items sums to NULL in SQL; we want 0.
    return query_one(
        "SELECT COALESCE(SUM(quantity * unit_price_paise), 0) AS t FROM order_items WHERE order_id = ?",
        (order_id,),
    )["t"]
