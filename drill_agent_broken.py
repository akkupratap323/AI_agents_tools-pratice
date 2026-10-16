"""DRILL (BROKEN VERSION - practice target): a WORKING customer-support agent with a WEAK tool layer.

The loop runs and the happy path works. Your job (tool-layer debugging exercise):
  1. READ the tools first (5 min). List every problem you can see before running anything.
  2. Run the scenarios below, watch the trace, find what breaks or silently lies.
  3. Harden the tool layer: schemas, descriptions, handlers, outputs, errors.
     The agent must recover cleanly and stay correct.

Answer key: drill_answers.md  (don't open it until you've done your own pass)

Uses its own database copy (drill.db) because issue_refund WRITES.
Reset to fresh data any time:  del drill.db   (it is re-copied from shop.db on next run)

Scenarios to try (python drill_agent_broken.py, then type them):
  1. How many orders has rahul verma placed?
  2. What's the total of order 5?
  3. What's the total of order 9999?
  4. What were our sales in January 2026?
  5. Refund order 5 in full.
  6. (ask 5 again, or say "do it again, I don't think it worked")
  7. Refund order 2.
  8. Show me all of Asha Rao's orders.
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
db.execute(
    "CREATE TABLE IF NOT EXISTS refunds ("
    " id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, amount INTEGER NOT NULL,"
    " created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)
db.commit()


# ───────────────────────────── tool handlers ─────────────────────────────

def find_customer(name):
    rows = db.execute(
        "SELECT id, name, email, city FROM customers WHERE name = ?", (name,)
    ).fetchall()
    return rows
print(find_customer("Asha Rao"))


def get_customer_orders(customer_id):
    rows = db.execute(
        "SELECT id, order_date, status FROM orders WHERE customer_id = ? ORDER BY order_date",
        (customer_id,),
    ).fetchall()
    return rows
print(get_customer_orders(1))


def get_order_total(order_id):
    status = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()[0]
    total = db.execute(
        "SELECT SUM(quantity * unit_price_paise) FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    return {"order_id": order_id, "total": total}


def sales_report(start_date, end_date):
    row = db.execute(
        "SELECT COUNT(DISTINCT o.id), SUM(oi.quantity * oi.unit_price_paise) "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.order_date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()
    return {"orders": row[0], "revenue": row[1]}


def issue_refund(order_id, amount):
    db.execute("INSERT INTO refunds (order_id, amount) VALUES (?, ?)", (order_id, amount))
    db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
    db.commit()
    return "Refund issued."


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


TOOLS = [
    _tool("find_customer", "Find a customer.",
          {"name": {"type": "string"}}, ["name"]),
    _tool("get_customer_orders", "Get orders.",
          {"customer_id": {"type": "string"}}, ["customer_id"]),
    _tool("get_order_total", "Get the total for an order.",
          {"order_id": {"type": "integer"}}, ["order_id"]),
    _tool("sales_report", "Sales numbers between two dates.",
          {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]),
    _tool("issue_refund", "Refund an order.",
          {"order_id": {"type": "integer"}, "amount": {"type": "number"}}, ["order_id", "amount"]),
]

SYSTEM = "You are a customer support agent for an online shop. Help with customer questions, orders and refunds."


# ───────────────────────────── agent loop ─────────────────────────────

def run_agent(messages):
    for turn in range(10):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        messages.append(msg)
        print(f"turn:{turn} -> {msg.content}")
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            print(f"  -> [turn] -> {tc.function.name}({args})")
            result = HANDLERS[tc.function.name](**args)
            print(f"  <- {str(result)[:300]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
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
