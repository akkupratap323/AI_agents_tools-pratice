# AI Agent Tool Design — Practice

Hands-on practice in **designing and hardening the tool layer of LLM agents**: tool schemas, handlers, error contracts, and the agent loop that ties them together. Everything runs against a small e-commerce database with deliberately messy data (mixed-case statuses, stray spaces in names, NULLs, money stored in paise).

## What's here

| File | What it is |
|---|---|
| `make_db.py` | Builds `shop.db` (SQLite): customers, products, orders, order_items, with realistic data traps |
| `make_pg.py` | Loads the same data into PostgreSQL |
| `q.py` | Tiny CLI to run SQL against `shop.db` |
| `hello_tool.py`, `loop.py` | First steps: a single tool call, then a full tool loop |
| `sql_agent.py` | Agent with `list_tables` / `describe_table` / `run_query` tools, hardened step by step |
| `attack.py` | Edge-case inputs fired directly at tool handlers (no model, no cost) |
| `drill_agent_broken.py` | A **working** support agent with a **weak** tool layer: the debugging exercise |
| `drill_answers.md` | What's wrong with it and why |
| `drill_agent_quickfix.py` | The minimal, high-impact fixes, each marked `# FIX:` |
| `drill_agent.py` | Fully hardened reference version, heavily commented |
| `support_agent/` | The same agent split into modules (one file per tool, startup contract check) |
| `support_tools.py`, `db_sqlite.py`, `db_postgres.py` | Provider- and database-agnostic tool layer |
| `agent_anthropic.py` | Agent on the Anthropic Messages API (`--db sqlite\|postgres`) |
| `agent_openai_responses.py` | Agent on the OpenAI Responses API (`--db sqlite\|postgres`) |

## Tool contract used throughout

1. Never crash the loop — every failure becomes a structured result the model can read.
2. "Not found" is an explicit error, never `[]`, `0` or `None`.
3. Errors say what failed **and** what to do next (a hint).
4. Named fields, units in the key names (`total_rupees`, not `total`).
5. Return the state that matters (e.g. an order's status).
6. Normalise messy data inside the tool.
7. Business rules live in code, not in the model's head.
8. Bound every list and flag truncation.
9. Write tools: validate → check state → idempotent → confirm → receipt.
10. The description matches the behaviour.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install openai python-dotenv httpx
python make_db.py                 # creates shop.db
```

Create a `.env` with the key for the provider you use:

```
DEEPSEEK_API_KEY=...      # drill_agent*.py, sql_agent.py, support_agent/
ANTHROPIC_API_KEY=...     # agent_anthropic.py   (pip install anthropic)
OPENAI_API_KEY=...        # agent_openai_responses.py
```

Postgres (optional):

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:17
pip install "psycopg[binary]"
python make_pg.py
```

## Run

```bash
python drill_agent.py                       # hardened agent (DeepSeek, SQLite)
python -m support_agent                     # same agent, modular layout
python agent_anthropic.py --db sqlite       # Anthropic Messages API
python agent_openai_responses.py --db postgres
```

Refunds write to a working copy (`support.db` / `drill.db`); delete it to reset the data.
