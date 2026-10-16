"""
tool_debug.py - find tool-layer bugs fast, WITHOUT calling the model (free).

Run the demo:  python tool_debug.py     (audits the tools in drill_agent_broken.py)

================================================================================
 STRATEGY - the same 7 steps for every tool
================================================================================
 1. PAIR      Put the schema next to the function.
              Same tool name? Same parameter names? Same required ones? Same types?
              -> check_contract(schema, function) does this for you.

 2. READ      Read the function line by line. For each line ask:
                a. What if nothing matches?   fetchone() -> None, fetchall() -> [], SUM -> None
                b. What if the input has a different shape?  case, spaces, format, "5" vs 5
                c. What UNIT is this value in?  paise or rupees? inclusive date?
                d. What is fetched but thrown away, or returned without a label?

 3. PROBE     Call the function directly with an input matrix (below).
              -> probe(fn, ...) and probe_many(fn, cases)

 4. JUDGE     For every output ask 3 questions:
                - Did it crash?                        (kills the loop)
                - Is it TRUE?                          (check with your own SQL)
                - Can the model ACT on it?             (named fields, units, clear error + hint)

 5. CLASSIFY  Fix in this order:
                1 crash   2 unsafe (money / writes / double actions)
                3 silent wrong answer   4 schema-function mismatch   5 too much output

 6. FIX       Lowest layer first: function code  ->  schema  ->  description  ->  prompt

 7. RE-PROBE  Same matrix again. Every crash -> an error dict. Every wrong -> right.

 INPUT MATRIX - what to try, per parameter type
   text / name :  exact | lowercase | extra spaces | partial | does not exist | ""
   id          :  exists | does not exist (9999) | 0 | -1 | "5" (a string)
   date        :  valid | wrong format ("January 2026") | start after end
   amount      :  valid | 0 | negative | too big | wrong unit
   write tool  :  valid | SAME CALL TWICE | wrong state (cancelled / already done)
   list output :  a case that returns MANY rows - is it capped?
================================================================================
"""

import inspect
import json


# ─────────────────────────────────────────────────────────────────────────────
# PROBE - call a tool function directly and show what happens
# ─────────────────────────────────────────────────────────────────────────────

def probe(fn, **kwargs):
    """Call fn(**kwargs). Prints OK + output, or CRASH + the error. Never raises."""
    try:
        out = fn(**kwargs)
        print(f"  OK     {fn.__name__}({kwargs}) -> {out!r}"[:220])
        return out
    except Exception as e:
        print(f"  CRASH  {fn.__name__}({kwargs}) -> {type(e).__name__}: {e}"[:220])
        return None


def probe_many(fn, cases):
    """cases = a list of kwargs dicts, e.g. [{"order_id": 5}, {"order_id": 9999}]"""
    print(f"\n=== probing {fn.__name__} ===")
    for kwargs in cases:
        probe(fn, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT CHECK - does the schema agree with the function?
# Catches: schema says "start", function says "start_date"  (always crashes)
#          a required param missing from "required"          (model may skip it)
# ─────────────────────────────────────────────────────────────────────────────

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


def check_all_contracts(tools, handlers):
    print("\n=== contract check (schema vs function) ===")
    for schema in tools:
        name = schema.get("function", schema).get("name")
        fn = handlers.get(name)
        if fn is None:
            print(f"  MISSING  {name}: schema exists but no function in handlers")
            continue
        check_contract(schema, fn)


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY CHECK - find the cause of a 400 Bad Request in the loop
# A 400 mid-loop almost always means the message history is malformed.
# ─────────────────────────────────────────────────────────────────────────────

def check_history_chat(messages):
    """Chat Completions: every tool_call id answered exactly once, in the right place."""
    print("\n=== history check (chat) ===")
    pending = set()                                   # call ids waiting for an answer
    ok = True
    for i, m in enumerate(messages):
        role = m["role"] if isinstance(m, dict) else m.role
        if role == "assistant":
            if pending:
                print(f"  [{i}] new assistant turn but calls never answered: {pending}"); ok = False
            calls = (m.get("tool_calls") if isinstance(m, dict) else m.tool_calls) or []
            pending = {c["id"] if isinstance(c, dict) else c.id for c in calls}
        elif role == "tool":
            if m["tool_call_id"] not in pending:
                print(f"  [{i}] tool result for unknown/answered id {m['tool_call_id']!r}"); ok = False
            pending.discard(m["tool_call_id"])
    if pending:
        print(f"  calls never answered: {pending}"); ok = False
    print("  history OK" if ok else "  -> fix the pairing above (that's your 400)")
    return ok


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


def show_messages(messages, max_chars=120):
    """Print the history compactly: one line per message."""
    print("\n=== messages ===")
    for i, m in enumerate(messages):
        role = m["role"] if isinstance(m, dict) else m.role
        body = m if isinstance(m, dict) else {"content": m.content, "tool_calls": m.tool_calls}
        print(f"  [{i}] {role:<9} {json.dumps(body, default=str)[:max_chars]}")


# ─────────────────────────────────────────────────────────────────────────────
# DEMO - audit the weak drill agent's tools (no API calls, no cost)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import drill_agent_broken as agent

    # Step 1: PAIR
    check_all_contracts(agent.TOOLS, agent.HANDLERS)

    # Step 3: PROBE with the input matrix
    probe_many(agent.find_customer, [
        {"name": "Asha Rao"}, {"name": "asha rao"}, {"name": "Rahul Verma"}, {"name": "Nobody"}, {"name": ""},
    ])
    probe_many(agent.get_order_total, [
        {"order_id": 5}, {"order_id": 9999}, {"order_id": 0},
    ])
    probe_many(agent.sales_report, [
        {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        {"start_date": "January 2026", "end_date": "January 2026"},
    ])

    # History check examples: a correct history and the classic forgotten-append bug
    good = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}, {"id": "c2"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{}"},
            {"role": "tool", "tool_call_id": "c2", "content": "{}"}]
    check_history_chat(good)
    bad = [{"role": "user", "content": "q"},
           {"role": "tool", "tool_call_id": "c1", "content": "{}"}]       # assistant turn never appended
    check_history_chat(bad)

    print("\nNow JUDGE each line above: crash? true? can the model act on it?")
