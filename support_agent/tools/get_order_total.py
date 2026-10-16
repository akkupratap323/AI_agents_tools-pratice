"""
get_order_total - one order's facts.

What the weak version got wrong, and how this fixes it:
  - fetchone()[0] crashed on a missing id     -> require_order() raises order_not_found
  - "total" was paise, unlabeled (100x wrong)  -> total_rupees: the unit is in the key
  - status was fetched and thrown away         -> status is returned, so the model
                                                 can say "that order was cancelled"
"""

from ..db import query_one
from ..helpers import order_total_paise, positive_int, require_order, rupees
from ._base import ToolSpec


def get_order_total(order_id):
    positive_int(order_id, "order_id")
    order = require_order(order_id)
    refund = query_one("SELECT amount_paise FROM refunds WHERE order_id = ?", (order_id,))
    return {
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "order_date": order["order_date"],
        "status": order["status"],
        "total_rupees": rupees(order_total_paise(order_id)),
        "refunded_rupees": rupees(refund["amount_paise"]) if refund else 0.0,
    }


SPEC = ToolSpec(
    name="get_order_total",
    description=(
        "Get one order's facts: status (delivered/shipped/cancelled/refunded), order_date, "
        "total_rupees and refunded_rupees. Always mention the status when it is cancelled or "
        "refunded. Errors: order_not_found."
    ),
    properties={
        "order_id": {"type": "integer", "description": "Numeric order id, e.g. 42."},
    },
    required=["order_id"],
    handler=get_order_total,
)
