"""
support_agent - the hardened customer-support agent, split into modules.

Same behaviour as the single-file drill_agent.py; this layout is how you would
organise it in a real codebase. Run from the project folder:

    python -m support_agent

Layout (dependencies only point DOWN this list - no cycles):

    __main__.py      entry point for `python -m support_agent`
    cli.py           chat REPL: reads input, keeps history, handles API errors
    agent.py         the agent loop: model <-> tools until a final answer
    dispatcher.py    safety net: any tool call -> JSON result, never raises
    tools/           ONE FILE PER TOOL (schema + handler side by side)
      __init__.py    registry: collects tools, checks schema == handler signature
      _base.py       ToolSpec dataclass + schema builder
      find_customer.py, get_customer_orders.py, get_order_total.py,
      sales_report.py, issue_refund.py
    helpers.py       validation / formatting / shared order lookups
    errors.py        ToolError: how a tool reports an expected failure
    db.py            SQLite connection, query timeout, refunds table
    llm.py           the model client (DeepSeek, Chat Completions)
    prompts.py       the system prompt
    config.py        every limit, path and business rule in one place

To add a tool: create tools/<name>.py exposing SPEC, then add it to TOOL_MODULES
in tools/__init__.py. Nothing else changes.
"""
