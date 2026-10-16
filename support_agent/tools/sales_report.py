"""
sales_report - orders and revenue for an inclusive date range.

Business rule (lives HERE, not in the prompt): revenue excludes cancelled and
refunded orders. The output says so (excluded_statuses) and includes a
per-status breakdown, so the model can explain the number it reports.

Dates are validated (ISO YYYY-MM-DD). The weak version accepted "January 2026",
which compared as text and silently returned 0 orders.
"""

from ..config import REVENUE_EXCLUDED_STATUSES
from ..db import query, query_one
from ..errors import ToolError
from ..helpers import parse_date, rupees
from ._base import ToolSpec


def sales_report(start_date, end_date):
    start = parse_date(start_date, "start_date")
    end = parse_date(end_date, "end_date")
    if start > end:
        raise ToolError("invalid_range", f"start_date {start} is after end_date {end}.", hint="Swap the dates.")

    # SQLite stores dates as ISO text, so text comparison == date comparison.
    period = (start.isoformat(), end.isoformat())
    excluded = ", ".join("?" for _ in REVENUE_EXCLUDED_STATUSES)

    totals = query_one(
        "SELECT COUNT(DISTINCT o.id) AS orders, "
        "       COALESCE(SUM(oi.quantity * oi.unit_price_paise), 0) AS revenue_paise "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.order_date BETWEEN ? AND ? "
        f"  AND LOWER(TRIM(o.status)) NOT IN ({excluded})",
        period + REVENUE_EXCLUDED_STATUSES,
    )
    by_status = query(
        "SELECT LOWER(TRIM(status)) AS status, COUNT(*) AS orders FROM orders "
        "WHERE order_date BETWEEN ? AND ? GROUP BY LOWER(TRIM(status)) ORDER BY status",
        period,
    )
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),                  # inclusive
        "orders": totals["orders"],
        "revenue_rupees": rupees(totals["revenue_paise"]),
        "excluded_statuses": list(REVENUE_EXCLUDED_STATUSES),
        "orders_by_status": by_status,
    }


SPEC = ToolSpec(
    name="sales_report",
    description=(
        "Sales for an inclusive date range. Returns orders and revenue_rupees EXCLUDING cancelled "
        "and refunded orders, plus orders_by_status for all statuses. "
        "Errors: invalid_date, invalid_range."
    ),
    properties={
        "start_date": {"type": "string", "description": "First day, YYYY-MM-DD, e.g. 2026-01-01."},
        "end_date": {"type": "string", "description": "Last day (inclusive), YYYY-MM-DD, e.g. 2026-01-31."},
    },
    required=["start_date", "end_date"],
    handler=sales_report,
)
