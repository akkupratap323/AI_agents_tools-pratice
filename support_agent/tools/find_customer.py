"""
find_customer - look a customer up by name.

Data traps this tool absorbs (so the model never has to know about them):
  'Rahul Verma '  trailing space      'Priya  Nair'  double space
  'vikram shah'   lowercase           'ARJUN MEHTA'  uppercase
Without normalisation, 3 real customers return [] and the model says
"no such customer" with confidence.
"""

from ..config import HARD_MAX_LIST_ROWS
from ..db import query
from ..errors import ToolError
from ..helpers import clean_display, normalize_name
from ._base import ToolSpec

# Normalise the COLUMN the same way normalize_name() normalises the INPUT:
# REPLACE collapses double spaces, TRIM drops the edges, LOWER ignores case.
_NORMALIZED_NAME = "LOWER(TRIM(REPLACE(name, '  ', ' ')))"


def find_customer(name):
    key = normalize_name(name)
    if not key:
        raise ToolError("empty_name", "Customer name is empty.", hint="Ask the user for the customer's name.")

    rows = query(f"SELECT id, name, email, city FROM customers WHERE {_NORMALIZED_NAME} = ?", (key,))
    match_type = "exact"
    if not rows:
        # Fallback: partial match, so 'asha' still finds 'Asha Rao'. Bounded.
        rows = query(
            f"SELECT id, name, email, city FROM customers WHERE {_NORMALIZED_NAME} LIKE ? LIMIT ?",
            (f"%{key}%", HARD_MAX_LIST_ROWS),
        )
        match_type = "partial"

    if not rows:
        # "Not found" is an explicit error, never [] (which looks like success).
        raise ToolError("customer_not_found", f"No customer matching {name!r}.",
                        hint="Ask the user to confirm the spelling, or for an email address.")

    customers = [{**r, "name": clean_display(r["name"])} for r in rows]
    result = {"match_type": match_type, "count": len(customers), "customers": customers}
    if len(customers) > 1:
        result["note"] = "Several customers match. Ask the user which one before acting on any of them."
    return result


SPEC = ToolSpec(
    name="find_customer",
    description=(
        "Look up customers by name. Matching ignores case and extra spaces, and falls back to a "
        "partial match. Returns customers (id, name, email, city) and match_type. Use the id with "
        "other tools. If several customers match, ask the user which one. "
        "Errors: customer_not_found, empty_name."
    ),
    properties={
        "name": {"type": "string", "description": "Name as the user gave it, e.g. 'Asha Rao' or 'asha'."},
    },
    required=["name"],
    handler=find_customer,
)
