"""QUICK-FIX version of drill_agent_broken.py - the minimal, high-impact fixes (~45 min of work).

Every change is marked  # FIX:  so you can diff it against the broken file.
Further hardening that is not coded here is listed at the bottom of this file.

Run: python drill_agent_quickfix.py      Reset data: del drill.db
"""
import json
import os
import shutil
import sqlite3

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0")),
    timeout=60,
)
MODEL = "deepseek-chat"

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "drill.db")
if not os.path.exists(DB_PATH):
    shutil.copy(os.path.join(HERE, "shop.db"), DB_PATH)

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row  # FIX: rows as dicts -> named fields in tool output
db.execute(
    "CREATE TABLE IF NOT EXISTS refunds ("
    " id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, amount INTEGER NOT NULL,"
    " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)
db.commit()


# FIX: one helper for "expected" errors - the model reads it and recovers
def tool_error(code, message, hint):
    return {"error": code, "message": message, "hint": hint}


# ───────────────────────────── tool handlers ─────────────────────────────

def find_customer(name):
    key = " ".join(name.split()).lower()  # FIX: normalise input (case + spaces)
    rows = db.execute(
        "SELECT id, name, email, city FROM customers "
        "WHERE LOWER(TRIM(REPLACE(name, '  ', ' '))) = ?",  # FIX: normalise the column too
        (key,),
    ).fetchall()
    if not rows:  # FIX: not found is an explicit error, not []
        return tool_error("customer_not_found", f"No customer named {name!r}.",
                          "Ask the user to confirm the spelling.")
    return {"customers": [dict(r) for r in rows]}  # FIX: named fields, not tuples


def get_customer_orders(customer_id, limit=20):
    limit = min(limit, 50)  # FIX: bounded output
    total = db.execute("SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,)).fetchone()[0]
    rows = db.execute(
        "SELECT id, order_date, LOWER(status) AS status FROM orders "  # FIX: normalised status
        "WHERE customer_id = ? ORDER BY order_date DESC LIMIT ?",
        (customer_id, limit),
    ).fetchall()
    return {"total_orders": total, "returned": len(rows),  # FIX: true count + truncation flag
            "truncated": len(rows) < total, "orders": [dict(r) for r in rows]}


def get_order_total(order_id):
    row = db.execute("SELECT LOWER(status) AS status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:  # FIX: was fetchone()[0] -> TypeError crash on a missing id
        return tool_error("order_not_found", f"No order {order_id}.", "Check the order id with the user.")
    paise = db.execute(
        "SELECT COALESCE(SUM(quantity * unit_price_paise), 0) FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    # FIX: unit in the key name (was paise labelled "total" -> 100x wrong) + status returned
    return {"order_id": order_id, "status": row["status"], "total_rupees": paise / 100}


def sales_report(start_date, end_date):
    if len(start_date) != 10 or len(end_date) != 10:  # FIX: "January 2026" silently gave 0
        return tool_error("invalid_date", "Dates must be YYYY-MM-DD.",
                          "e.g. January 2026 -> 2026-01-01 to 2026-01-31")
    row = db.execute(
        "SELECT COUNT(DISTINCT o.id), COALESCE(SUM(oi.quantity * oi.unit_price_paise), 0) "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.order_date BETWEEN ? AND ? "
        "AND LOWER(o.status) NOT IN ('cancelled', 'refunded')",  # FIX: business rule
        (start_date, end_date),
    ).fetchone()
    return {"orders": row[0], "revenue_rupees": row[1] / 100,  # FIX: rupees, labelled
            "excludes": ["cancelled", "refunded"]}


def issue_refund(order_id, amount_rupees):  # FIX: unit in the parameter name
    order = db.execute("SELECT LOWER(status) AS status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:  # FIX: order must exist
        return tool_error("order_not_found", f"No order {order_id}.", "Check the order id.")
    existing = db.execute("SELECT id, amount FROM refunds WHERE order_id = ?", (order_id,)).fetchone()
    if existing:  # FIX: idempotent - a retry returns the same refund, never a second one
        return {"already_refunded": True, "refund_id": existing["id"], "amount_rupees": existing["amount"] / 100}
    if order["status"] not in ("delivered", "shipped"):  # FIX: state check
        return tool_error("not_refundable", f"Order {order_id} is {order['status']}.",
                          "Only delivered or shipped orders can be refunded. Tell the user why.")
    total = get_order_total(order_id)["total_rupees"]
    if amount_rupees <= 0 or amount_rupees > total:  # FIX: amount within limits
        return tool_error("invalid_amount", f"Amount must be between 0 and {total}.", "Refund at most the total.")
    with db:  # FIX: both writes in one transaction
        cur = db.execute("INSERT INTO refunds (order_id, amount) VALUES (?, ?)",
                         (order_id, round(amount_rupees * 100)))
        db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
    return {"refunded": True, "refund_id": cur.lastrowid,  # FIX: a receipt, not "Refund issued."
            "order_id": order_id, "amount_rupees": amount_rupees}


HANDLERS = {
    "find_customer": find_customer,
    "get_customer_orders": get_customer_orders,
    "get_order_total": get_order_total,
    "sales_report": sales_report,
    "issue_refund": issue_refund,
}


# ───────────────────────────── tool schemas ─────────────────────────────

def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


# FIX: every description now says what / returns / errors; names and types match the handlers
TOOLS = [
    _tool("find_customer",
          "Find customers by name (case/space-insensitive). Returns id, name, email, city. "
          "Error customer_not_found.",
          {"name": {"type": "string", "description": "e.g. 'Asha Rao'"}}, ["name"]),
    _tool("get_customer_orders",
          "A customer's orders, newest first. total_orders is the true count; max 50 rows, "
          "truncated=true means more exist.",
          {"customer_id": {"type": "integer"},  # FIX: was string
           "limit": {"type": "integer", "description": "default 20, max 50"}}, ["customer_id"]),
    _tool("get_order_total",
          "One order's status and total_rupees. Mention the status if cancelled/refunded. "
          "Error order_not_found.",
          {"order_id": {"type": "integer"}}, ["order_id"]),
    _tool("sales_report",
          "Orders and revenue_rupees for an inclusive date range, excluding cancelled and refunded orders.",
          {"start_date": {"type": "string", "description": "YYYY-MM-DD"},  # FIX: was "start"
           "end_date": {"type": "string", "description": "YYYY-MM-DD"}},    # FIX: was "end"
          ["start_date", "end_date"]),
    _tool("issue_refund",
          "Refund a delivered/shipped order, amount in RUPEES, at most the order total. One refund per "
          "order: repeat calls return the existing refund. Irreversible - confirm with the user first.",
          {"order_id": {"type": "integer"},
           "amount_rupees": {"type": "number", "description": "rupees, not paise"}},  # FIX: unit
          ["order_id", "amount_rupees"]),
]

SYSTEM = ("You are a customer support agent for an online shop. Use tools for every fact. "
          "If a tool returns an error, follow its hint. "  # FIX: business policy in the prompt
          "Always confirm the amount with the user before calling issue_refund.")


# ───────────────────────────── agent loop ─────────────────────────────

def run_tool(name, raw_args):
    """FIX: the safety net - any failure becomes a result the model can read, never a crash."""
    handler = HANDLERS.get(name)  # FIX: was HANDLERS[name] -> KeyError crash
    if handler is None:
        return {"error": "unknown_tool", "available": list(HANDLERS)}
    try:
        return handler(**json.loads(raw_args))  # FIX: bad JSON / wrong args no longer crash
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


def run_agent(messages):
    for turn in range(10):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            print(f"  [turn {turn}] -> {tc.function.name}({tc.function.arguments})")
            result = run_tool(tc.function.name, tc.function.arguments)
            print(f"  [turn {turn}] <- {str(result)[:300]}")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, default=str)})  # FIX: was str(result)
    return "(gave up after 10 turns)"


def main():
    messages = [{"role": "system", "content": SYSTEM}]
    print("Support agent. /reset clears memory, /exit quits.\n")
    while True:
        try:
            q = input("you: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not q:
            continue
        if q == "/exit":
            break
        if q == "/reset":
            messages = [{"role": "system", "content": SYSTEM}]
            continue
        messages.append({"role": "user", "content": q})
        print(f"\nagent: {run_agent(messages)}\n")


if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────────────────────
# NOT IMPLEMENTED HERE - next hardening steps (see drill_agent.py for full versions):
#   - two-step confirmation for refunds (preview -> user confirms -> execute),
#     ideally a real UI confirm, not the model's word
#   - UNIQUE(order_id) on refunds so two racing requests can't double-refund
#   - query timeout, so a runaway query can't hang the agent
#   - stop when the same failing call repeats (wasted turns, money)
#   - validate args against the schema before calling (or strict mode on Anthropic)
#   - partial-match fallback + "several customers match, ask which one"
#   - tests for each tool: not found, bad input, retry, boundary values
# ─────────────────────────────────────────────────────────────────────────────
