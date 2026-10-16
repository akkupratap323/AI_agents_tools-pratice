"""
tools/ - the tool registry.

Collects every tool module's SPEC and builds:
    HANDLERS   name -> handler function   (used by the dispatcher)
    TOOLS      wire-format schemas          (sent to the model)

At import time it VERIFIES each tool's contract, so a broken tool fails loudly
at startup instead of silently at 2am in front of a user:
    - names are unique
    - every schema property is a handler parameter, and vice versa
    - `required` == the handler parameters that have no default value
This is the automated version of "put the schema and the handler side by side".
"""

import inspect

from . import find_customer, get_customer_orders, get_order_total, issue_refund, sales_report

TOOL_MODULES = [find_customer, get_customer_orders, get_order_total, sales_report, issue_refund]
SPECS = [m.SPEC for m in TOOL_MODULES]


def _check_contract(spec):
    params = inspect.signature(spec.handler).parameters
    handler_params = set(params)
    schema_params = set(spec.properties)
    no_default = {n for n, p in params.items() if p.default is inspect.Parameter.empty}

    if handler_params != schema_params:
        raise RuntimeError(
            f"Tool '{spec.name}': schema properties {sorted(schema_params)} != "
            f"handler parameters {sorted(handler_params)}")
    if set(spec.required) != no_default:
        raise RuntimeError(
            f"Tool '{spec.name}': required {sorted(spec.required)} != "
            f"handler parameters without defaults {sorted(no_default)}")


_names = [s.name for s in SPECS]
if len(_names) != len(set(_names)):
    raise RuntimeError(f"Duplicate tool names: {_names}")
for _spec in SPECS:
    _check_contract(_spec)

HANDLERS = {s.name: s.handler for s in SPECS}
TOOLS = [s.to_chat_completions() for s in SPECS]
