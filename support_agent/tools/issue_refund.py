"""
issue_refund - the dangerous tool (moves money, irreversible).

Order of checks - and why the order matters:
  1. validate input            positive id, positive amount in RUPEES
  2. order exists              else order_not_found
  3. IDEMPOTENCY (before state) an existing refund is returned, never duplicated.
                               After a refund the status is 'refunded', so checking
                               status first would wrongly answer a harmless retry
                               ("do it again, I don't think it worked") with
                               "not refundable".
  4. state                     only delivered / shipped orders
  5. amount                    <= order total
  6. confirm gate              without confirm=true: return a preview, write nothing
  7. atomic write              INSERT refund + UPDATE status in ONE transaction
  8. receipt                   refund_id, amount, new_status - something to verify

Defence in depth for duplicates: the check in step 3, plus UNIQUE(order_id) on
the refunds table (db.py), which catches two identical requests that race.
"""

from ..config import REFUNDABLE_STATUSES
from ..db import IntegrityError, conn, query_one
from ..errors import ToolError
from ..helpers import order_total_paise, positive_int, require_order, rupees
from ._base import ToolSpec


def _existing_refund_receipt(order_id, existing):
    return {"already_refunded": True, "refund_id": existing["id"], "order_id": order_id,
            "amount_rupees": rupees(existing["amount_paise"]),
            "note": "This order was already refunded. No new refund was created."}


def issue_refund(order_id, amount_rupees, confirm=False):
    # 1. validate
    positive_int(order_id, "order_id")
    if isinstance(amount_rupees, bool) or not isinstance(amount_rupees, (int, float)) or amount_rupees <= 0:
        raise ToolError("invalid_amount", f"amount_rupees must be a positive number, got {amount_rupees!r}.",
                        hint="Use get_order_total to find the order's total in rupees.")
    amount_paise = round(amount_rupees * 100)

    # 2. exists
    order = require_order(order_id)

    # 3. idempotency
    existing = query_one("SELECT id, amount_paise FROM refunds WHERE order_id = ?", (order_id,))
    if existing:
        return _existing_refund_receipt(order_id, existing)

    # 4. state
    if order["status"] not in REFUNDABLE_STATUSES:
        raise ToolError("not_refundable",
                        f"Order {order_id} has status '{order['status']}' and cannot be refunded.",
                        hint="Only delivered or shipped orders can be refunded. Tell the user why.",
                        current_status=order["status"])

    # 5. amount
    total_paise = order_total_paise(order_id)
    if amount_paise > total_paise:
        raise ToolError("amount_exceeds_total",
                        f"Refund Rs {rupees(amount_paise)} exceeds the order total Rs {rupees(total_paise)}.",
                        hint="Refund at most the order total.", max_refundable_rupees=rupees(total_paise))

    # 6. confirm gate
    if not confirm:
        # In a real product the confirmation should come from the UI (a human
        # clicking "Confirm"), not from the model setting a flag. Here the
        # description + this response make the model ask the user first.
        return {"requires_confirmation": True,
                "preview": {"order_id": order_id, "status": order["status"],
                            "order_total_rupees": rupees(total_paise),
                            "refund_rupees": rupees(amount_paise)},
                "hint": "Show this to the user and ask them to confirm. "
                        "Only after they say yes, call issue_refund again with confirm=true."}

    # 7. atomic write
    try:
        with conn:   # one transaction: both statements commit together, or neither does
            cur = conn.execute("INSERT INTO refunds (order_id, amount_paise) VALUES (?, ?)",
                               (order_id, amount_paise))
            conn.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
    except IntegrityError:
        # UNIQUE(order_id) fired: an identical request won the race. Still idempotent.
        return _existing_refund_receipt(
            order_id, query_one("SELECT id, amount_paise FROM refunds WHERE order_id = ?", (order_id,)))

    # 8. receipt
    return {"refunded": True, "refund_id": cur.lastrowid, "order_id": order_id,
            "amount_rupees": rupees(amount_paise), "new_status": "refunded"}


SPEC = ToolSpec(
    name="issue_refund",
    description=(
        "Refund an order (irreversible money movement). Only delivered or shipped orders; amount "
        "must not exceed the order total; one refund per order (repeat calls return the existing "
        "refund, never a second one). Call first WITHOUT confirm to get a preview, show it to the "
        "user, and call again with confirm=true only after they explicitly agree. Returns a receipt "
        "(refund_id, amount_rupees, new_status). Errors: order_not_found, not_refundable, "
        "amount_exceeds_total, invalid_amount."
    ),
    properties={
        "order_id": {"type": "integer", "description": "Numeric order id, e.g. 42."},
        "amount_rupees": {"type": "number", "description": "Refund in RUPEES (not paise), e.g. 21896.0."},
        "confirm": {"type": "boolean", "description": "true only after the user confirmed the preview."},
    },
    required=["order_id", "amount_rupees"],
    handler=issue_refund,
)
