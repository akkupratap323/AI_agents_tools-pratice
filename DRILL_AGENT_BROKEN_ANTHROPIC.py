"""DRILL (BROKEN VERSION, ANTHROPIC SETUP - practice target): a WORKING customer-support agent with a WEAK tool layer.

Same tools, same planted bugs and same debug helpers as drill_agent_broken.py.
Only the model API is different: Anthropic Messages instead of Chat Completions.

What changed vs drill_agent_broken.py (only the API layer):
  client        anthropic.Anthropic()                instead of OpenAI(base_url=deepseek)
  _tool         {name, description, input_schema}    instead of {type: function, function: {...parameters}}
  system prompt system=SYSTEM on every request        instead of a {"role": "system"} message
  run_agent     stop_reason / content blocks / ONE user message with all tool_results (+ is_error)
  history check check_history_anthropic              instead of check_history_chat
  tracing       AnthropicInstrumentor                 instead of OpenAIInstrumentor

The loop runs and the happy path works. Your job (tool-layer debugging exercise):
  1. READ the tools first (5 min). List every problem you can see before running anything.
  2. Run the scenarios below, watch the trace, find what breaks or silently lies.
  3. Harden the tool layer: schemas, descriptions, handlers, outputs, errors.
     The agent must recover cleanly and stay correct.

Answer key: drill_answers.md  (don't open it until you've done your own pass)

Setup:  pip install anthropic openinference-instrumentation-anthropic
        ANTHROPIC_API_KEY=... in .env
Uses its own database copy (drill.db) because issue_refund WRITES.
Reset to fresh data any time:  del drill.db   (it is re-copied from shop.db on next run)

Scenarios to try (python DRILL_AGENT_BROKEN_ANTHROPIC.py, then type them):
  1. How many orders has rahul verma placed?
  2. What's the total of order 5?
  3. What's the total of order 9999?
  4. What were our sales in January 2026?
  5. Refund order 5 in full.
  6. (ask 5 again, or say "do it again, I don't think it worked")
  7. Refund order 2.
  8. Show me all of Asha Rao's orders.
"""
import json,inspect
import os
import shutil
import sqlite3
from tool_debug import probe, probe_many, check_all_contracts, check_history_anthropic
from tool_dispatcher import run_tool, tool_error

import anthropic
from dotenv import load_dotenv

load_dotenv()

from phoenix.otel import register
from openinference.instrumentation.anthropic import AnthropicInstrumentor

tracer_provider = register(project_name="tool-drill")                 # ONE register only
AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)   # traces every model call
tracer = tracer_provider.get_tracer(__name__)



client = anthropic.Anthropic(timeout=60)      # reads ANTHROPIC_API_KEY from the environment
MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000                            # required on every Anthropic request

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


def tool_error(code, message, hint=None):
    error = {"error": code, "message": message}
    if hint:
        error["hint"] = hint
    return error

#probe

def check_contract(schema, fn):
    """Accepts a Chat Completions schema ({"function": {...}}) or an Anthropic one."""
    spec = schema.get("function", schema)                   # unwrap the chat format
    params_schema = spec.get("parameters") or spec.get("input_schema") or {}
    schema_params = set(params_schema.get("properties", {}))
    schema_required = set(params_schema.get("required", []))

    sig = inspect.signature(fn).parameters
    fn_params = set(sig)
    fn_required = {n for n, p in sig.items() if p.default is inspect.Parameter.empty}

    problems = []
    if spec.get("name") != fn.__name__:
        problems.append(f"name: schema '{spec.get('name')}' vs function '{fn.__name__}'")
    if schema_params - fn_params:
        problems.append(f"in schema but NOT in function: {sorted(schema_params - fn_params)}")
    if fn_params - schema_params:
        problems.append(f"in function but NOT in schema: {sorted(fn_params - schema_params)}")
    if fn_required - schema_required:
        problems.append(f"function requires these but schema doesn't: {sorted(fn_required - schema_required)}")
    if len(spec.get("description", "")) < 40:
        problems.append(f"description too short: {spec.get('description')!r}")

    label = spec.get("name")
    if problems:
        print(f"  MISMATCH {label}:")
        for p in problems:
            print(f"     - {p}")
    else:
        print(f"  ok       {label}")
    return problems

def probe(fn, **kwargs):
    """Call fn(**kwargs). Prints OK + output, or CRASH + the error. Never raises."""
    try:
        out = fn(**kwargs)
        print(f"  OK     {fn.__name__}({kwargs}) -> {out!r}"[:220])
        return out
    except Exception as e:
        print(f"  CRASH  {fn.__name__}({kwargs}) -> {type(e).__name__}: {e}"[:220])
        return None

def check_all_contracts(tools, handlers):
    print("\n=== contract check (schema vs function) ===")
    for schema in tools:
        name = schema.get("function", schema).get("name")
        fn = handlers.get(name)
        if fn is None:
            print(f"  MISSING  {name}: schema exists but no function in handlers")
            continue
        check_contract(schema, fn)
# ───────────────────────────── tool handlers ─────────────────────────────
@tracer.tool
def find_customer(name):
    rows = db.execute(
        "SELECT id, name, email, city FROM customers WHERE name = ?", (name,)
    ).fetchall()
    return rows

@tracer.tool
def get_customer_orders(customer_id):
    rows = db.execute(
        "SELECT id, order_date, status FROM orders WHERE customer_id = ? ORDER BY order_date",
        (customer_id,),
    ).fetchall()
    return rows


@tracer.tool
def get_order_total(order_id):
    status = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()[0]
    total = db.execute(
        "SELECT SUM(quantity * unit_price_paise) FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    return {"order_id": order_id, "total": total}

@tracer.tool
def sales_report(start_date, end_date):
    row = db.execute(
        "SELECT COUNT(DISTINCT o.id), SUM(oi.quantity * oi.unit_price_paise) "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.order_date BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()
    return {"orders": row[0], "revenue": row[1]}

@tracer.tool
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
    # Anthropic shape: no {"type": "function", "function": ...} wrapper,
    # and the JSON Schema goes under "input_schema" (not "parameters").
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "required": required},
    }


def run_tool(handlers, name, args):
    """Run one tool call. Returns (result_dict, is_error). Never raises.

    handlers : dict of  tool name -> python function
    name     : the tool name the model asked for
    args     : dict (Anthropic) OR json string (OpenAI / DeepSeek)
    """
    # Step 1: does the tool exist?   (handlers[name] would raise KeyError and kill the loop)
    handler = handlers.get(name)
    if handler is None:
        return tool_error("unknown_tool", f"No tool named {name!r}.",
                          hint=f"Use one of: {', '.join(handlers)}"), True

    # Step 2: arguments -> dict.   OpenAI-style APIs send a JSON STRING, which can be broken.
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return tool_error("bad_arguments", f"Arguments are not valid JSON: {e}",
                              hint="Send the arguments as a JSON object."), True
    if not isinstance(args, dict):
        return tool_error("bad_arguments", "Arguments must be a JSON object.",
                          hint="Send the arguments as a JSON object."), True

    # Step 3: check the argument NAMES before calling.
    #   Why separately? If we just caught TypeError from the call, a crash INSIDE the
    #   function (e.g. None[0] on a missing row) would be wrongly reported as
    #   "wrong argument names" - and the model would chase the wrong fix.
    #   .bind() only checks names/count against the signature; it runs nothing.
    try:
        inspect.signature(handler).bind(**args)
    except TypeError as e:
        return tool_error("bad_arguments", str(e),
                          hint="Use exactly the parameter names from the tool schema."), True

    # Step 4: call it, and catch everything else.
    try:
        result = handler(**args)        # {"order_id": 5}  ->  handler(order_id=5)
    except Exception as e:
        # Anything else: a database error, a bug, a None[0]... report it, don't crash.
        return tool_error(type(e).__name__, str(e),
                          hint="Fix the input or tell the user the request failed."), True

    # Step 5: a handler may RETURN an error dict instead of raising - treat it as an error too.
    if isinstance(result, dict) and "error" in result:
        return result, True
    return result, False

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

def check_history_anthropic(messages):
    """Anthropic: every tool_use id gets a tool_result in the VERY NEXT user message."""
    print("\n=== history check (anthropic) ===")
    ok = True

    def blocks(m):
        content = m["content"]
        return content if isinstance(content, list) else []

    def field(b, key):
        return b[key] if isinstance(b, dict) else getattr(b, key, None)

    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        use_ids = {field(b, "id") for b in blocks(m) if field(b, "type") == "tool_use"}
        if not use_ids:
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        result_ids = {field(b, "tool_use_id") for b in blocks(nxt) if field(b, "type") == "tool_result"} \
            if nxt and nxt["role"] == "user" else set()
        if use_ids - result_ids:
            print(f"  [{i}] tool_use without tool_result in the next message: {use_ids - result_ids}"); ok = False
    print("  history OK" if ok else "  -> fix the pairing above (that's your 400)")
    return ok


def text_of(content):
    """The model's visible text: only the "text" blocks (skip thinking / tool_use blocks)."""
    return "".join(b.text for b in content if b.type == "text")


@tracer.agent
def run_agent(messages):
    for turn in range(10):
        try:
           resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
                                         tools=TOOLS, messages=messages)
        except Exception as e:
            print("API error",e)
            check_history_anthropic(messages)
            raise
        messages.append({"role": "assistant", "content": resp.content})   # the WHOLE content list
        print(f"turn:{turn} stop_reason={resp.stop_reason} -> {text_of(resp.content)}")
        if resp.stop_reason != "tool_use":
            return text_of(resp.content)
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            args = block.input                                             # already a dict
            print(f"  -> [turn] -> {block.name}({args})")
            result,is_error = run_tool(HANDLERS, block.name, args)
            print(f"[{'ERROR' if is_error else 'ok'}]  <- {str(result)[:300]}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(result), "is_error": is_error})
        messages.append({"role": "user", "content": results})             # ONE message, ALL results
    return "(gave up after 10 turns)"


def main():
    messages = []                     # Anthropic: the system prompt is NOT a message
    print("Support agent (Anthropic). /reset clears memory, /exit quits.\n")
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
            messages = []
            continue
        messages.append({"role": "user", "content": q})
        print(f"\nagent: {run_agent(messages)}\n")


if __name__ == "__main__":
    main()
