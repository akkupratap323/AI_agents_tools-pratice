"""
config.py - every knob in one place.

Production habit: limits and business rules are named constants, so a reviewer
can read the policy without reading the code, and changing a policy is a
one-line diff. Values that differ per environment come from env vars.
"""

import os

# ── model / loop ─────────────────────────────────────────────────────────────
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
API_BASE_URL = "https://api.deepseek.com"
API_TIMEOUT_SECONDS = 60
API_MAX_RETRIES = 2            # SDK retries 429 / 5xx / connection errors with backoff
MAX_TURNS = 10                 # model round-trips per user question (loop bound)

# ── tool output bounds ───────────────────────────────────────────────────────
MAX_LIST_ROWS = 20             # default page size for list tools
HARD_MAX_LIST_ROWS = 50        # the model may ask for more, never above this
QUERY_TIMEOUT_SECONDS = 5.0    # a runaway query is aborted and reported, not waited on
MAX_REPEAT_FAILURES = 2        # an identical failing call is allowed this many times

# ── business rules (live in code, not in the model's head) ───────────────────
REVENUE_EXCLUDED_STATUSES = ("cancelled", "refunded")
REFUNDABLE_STATUSES = ("delivered", "shipped")

# ── logging ──────────────────────────────────────────────────────────────────
LOG_RESULT_CHARS = 400         # how much of each tool result to print in the trace

# ── paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_DIR, "support.db")      # working copy (refunds write here)
SEED_DB_PATH = os.path.join(PROJECT_DIR, "shop.db")    # never modified
