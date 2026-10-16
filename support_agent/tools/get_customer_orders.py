"""
get_customer_orders - a customer's orders, newest first, bounded.

Key design point: a capped list must never be mistaken for the whole list.
The output carries total_orders (the true COUNT) plus truncated + note, so the
model answers "how many orders?" with 131, not with the 20 rows it can see.
"""

from ..config import HARD_MAX_LIST_ROWS, MAX_LIST_ROWS
from ..db import query, query_one
from ..errors import ToolError
from ..helpers import clean_display, positive_int
from ._base import ToolSpec


def get_customer_orders(customer_id, limit=MAX_LIST_ROWS):
    positive_int(customer_id, "customer_id")
    limit = min(positive_int(limit, "limit"), HARD_MAX_LIST_ROWS)   # the model can't exceed the hard cap

    customer = query_one("SELECT id, name FROM customers WHERE id = ?", (customer_id,))
    if customer is None:
        raise ToolError("customer_not_found", f"No customer with id {customer_id}.",
                        hint="Look the customer up by name with find_customer to get the id.")

    total = query_one("SELECT COUNT(*) AS n FROM orders WHERE customer_id = ?", (customer_id,))["n"]
    orders = query(
        "SELECT id AS order_id, order_date, LOWER(TRIM(status)) AS status "   # status normalised
        "FROM orders WHERE customer_id = ? ORDER BY order_date DESC, id DESC LIMIT ?",
        (customer_id, limit),
    )

    result = {
        "customer_id": customer_id,
        "customer_name": clean_display(customer["name"]),
        "total_orders": total,
        "returned": len(orders),
        "truncated": len(orders) < total,
        "orders": orders,
    }
    if result["truncated"]:
        result["note"] = (f"Showing the {len(orders)} most recent of {total} orders. "
                          f"Use total_orders for counts; do not count the list.")
    return result


SPEC = ToolSpec(
    name="get_customer_orders",
    description=(
        f"List a customer's orders, newest first. Returns customer_name, total_orders (the true "
        f"count - use it for 'how many' questions), and up to `limit` orders (order_id, order_date, "
        f"status). Default {MAX_LIST_ROWS}, max {HARD_MAX_LIST_ROWS}; truncated=true means more exist. "
        f"Errors: customer_not_found."
    ),
    properties={
        "customer_id": {"type": "integer", "description": "Numeric customer id from find_customer, e.g. 12."},
        "limit": {"type": "integer", "description": f"Max orders to return (1-{HARD_MAX_LIST_ROWS}). Optional."},
    },
    required=["customer_id"],
    handler=get_customer_orders,
)
