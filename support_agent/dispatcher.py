"""
dispatcher.py - the safety net between the model and the tools.

dispatch(name, raw_arguments) -> (json_string, is_error)   and it NEVER raises.

Every way a tool call can go wrong becomes a JSON result the model can read
and recover from, instead of an exception that kills the agent loop:

    unknown tool name            -> unknown_tool  (+ the list of real tools)
    arguments not valid JSON     -> bad_arguments
    wrong / missing / extra args -> bad_arguments (TypeError from the call)
    expected failure             -> the ToolError's code, message and hint
    DB error or query timeout    -> database_error
    a bug in our own code        -> internal_error (logged, details NOT leaked)
    same failing call repeated   -> repeated_failure (stops wasted turns)
"""

import json

from .config import MAX_REPEAT_FAILURES
from .db import OperationalError
from .errors import ToolError
from .tools import HANDLERS

# (tool name, canonical args JSON) -> how many times that exact call has failed.
# Cleared by reset() when the user starts a new conversation.
_failure_counts = {}


def reset():
    _failure_counts.clear()


def dispatch(name, raw_arguments):
    handler = HANDLERS.get(name)
    if handler is None:
        return _error({"error": "unknown_tool", "message": f"No tool named {name!r}.",
                       "available_tools": sorted(HANDLERS)})

    # Chat Completions sends arguments as a JSON *string* - parsing can fail.
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        return _error({"error": "bad_arguments", "message": f"Arguments are not a valid JSON object: {e}",
                       "hint": "Resend the call with a JSON object matching the tool schema."})

    # Loop guard: retrying the exact same failing call burns turns and money.
    call_key = (name, json.dumps(args, sort_keys=True))
    if _failure_counts.get(call_key, 0) >= MAX_REPEAT_FAILURES:
        return _error({"error": "repeated_failure",
                       "message": f"This exact {name} call already failed {MAX_REPEAT_FAILURES} times.",
                       "hint": "Do not retry it unchanged. Change the arguments or explain the problem to the user."})

    try:
        result = handler(**args)
        return json.dumps(result, default=str), False
    except ToolError as e:
        payload = e.to_dict()
    except TypeError as e:
        payload = {"error": "bad_arguments", "message": str(e),
                   "hint": "Use exactly the parameter names in the tool schema."}
    except OperationalError as e:
        payload = {"error": "database_error", "message": str(e),
                   "hint": "The query failed or timed out. Try a narrower request."}
    except Exception as e:
        print(f"   !! internal error in {name}: {type(e).__name__}: {e}")
        payload = {"error": "internal_error", "message": "The tool failed unexpectedly.",
                   "hint": "Tell the user something went wrong; do not retry the same call."}

    _failure_counts[call_key] = _failure_counts.get(call_key, 0) + 1
    return _error(payload)


def _error(payload):
    return json.dumps(payload, default=str), True
