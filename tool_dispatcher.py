"""
tool_dispatcher.py - run ANY tool call safely. Independent: copy what you need.

THE ONE RULE: a tool call must NEVER crash the agent loop.
Whatever goes wrong, the model gets back a result it can read and act on.

    run_tool(handlers, name, args)  ->  (result_dict, is_error)     never raises

Then wrap that result in the shape your API needs:

    Chat Completions (DeepSeek / OpenAI chat):  chat_tool_message(tool_call, handlers)
    Anthropic Messages:                         anthropic_tool_results(response.content, handlers)
    OpenAI Responses:                           responses_tool_output(call, handlers)

Usage in a Chat Completions loop:

    for tc in msg.tool_calls:
        messages.append(chat_tool_message(tc, HANDLERS))

Usage in an Anthropic loop:

    messages.append({"role": "assistant", "content": resp.content})
    messages.append(anthropic_tool_results(resp.content, HANDLERS))
"""

import inspect
import json


# ─────────────────────────────────────────────────────────────────────────────
# 1. A standard error shape
#    Every error has the same keys, so the model always knows where to look.
#    "hint" is the most important part: it tells the model what to do NEXT.
# ─────────────────────────────────────────────────────────────────────────────

def tool_error(code, message, hint=None):
    error = {"error": code, "message": message}
    if hint:
        error["hint"] = hint
    return error


# ─────────────────────────────────────────────────────────────────────────────
# 2. The dispatcher
#    Checks, in order:  tool exists?  ->  args parse?  ->  arg names match?  ->  call it, catch everything
# ─────────────────────────────────────────────────────────────────────────────

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


def to_json(result):
    """Tool results must be real JSON text. default=str handles dates/Decimals that
    json.dumps can't serialize (a classic crash AFTER the query already worked)."""
    return json.dumps(result, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Wrap the result for each API format
#    The rule is the same everywhere: every call id gets EXACTLY ONE result.
# ─────────────────────────────────────────────────────────────────────────────

def chat_tool_message(tool_call, handlers):
    """Chat Completions: one {"role": "tool"} message PER tool call.
    No is_error field exists in this format, so the error lives inside content."""
    result, is_error = run_tool(handlers, tool_call.function.name, tool_call.function.arguments)
    log_call(tool_call.function.name, tool_call.function.arguments, result, is_error)
    return {"role": "tool", "tool_call_id": tool_call.id, "content": to_json(result)}


def anthropic_tool_results(content_blocks, handlers):
    """Anthropic: ONE user message containing a tool_result for EVERY tool_use block.
    (Splitting results across several messages is wrong; skipping a failed one -> 400.)"""
    results = []
    for block in content_blocks:
        if block.type != "tool_use":
            continue
        result, is_error = run_tool(handlers, block.name, block.input)   # input is already a dict
        log_call(block.name, block.input, result, is_error)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,           # must match the tool_use block's id
            "content": to_json(result),
            "is_error": is_error,              # tells the model this call failed
        })
    return {"role": "user", "content": results}


def responses_tool_output(call, handlers):
    """OpenAI Responses: one function_call_output item per function_call item."""
    result, is_error = run_tool(handlers, call.name, call.arguments)
    log_call(call.name, call.arguments, result, is_error)
    return {"type": "function_call_output", "call_id": call.call_id, "output": to_json(result)}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Logging - see exactly what went IN and what came OUT of every tool call
# ─────────────────────────────────────────────────────────────────────────────

def log_call(name, args, result, is_error, max_chars=300):
    status = "ERROR" if is_error else "ok"
    print(f"  -> {name}({args})")
    print(f"  <- [{status}] {to_json(result)[:max_chars]}")
