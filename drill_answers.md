# Drill answer key — don't open until you've done your own pass

Verified numbers (fresh drill.db):
- Rahul Verma is stored as `'Rahul Verma '` (trailing space) → 22 orders
- Order 5: status **cancelled**, total 2,189,600 **paise** = ₹21,896
- Order 2: status **refunded** already
- Jan 2026: tool says 41 orders / 46,907,900 paise. Excluding cancelled+refunded: **30 orders, ₹3,59,592**
- Asha Rao (id 1): 131 orders

## Loop-level (the agent must not die)

| # | Problem | Symptom | Fix |
|---|---|---|---|
| L1 | No try/except around `HANDLERS[...](**args)` | Any handler exception kills the whole chat | `safe_call` → return `{"error", "message", "hint"}` |
| L2 | `HANDLERS[name]` | Unknown tool → `KeyError` crash | `.get()` + error listing available tools |
| L3 | `json.loads` unguarded | Malformed args → crash | try/except → error result |
| L4 | `str(result)` | Python repr (`None`, single quotes, tuples) instead of JSON | `json.dumps(result, default=str)` |

## Tool-level

### find_customer
| Problem | Symptom | Fix |
|---|---|---|
| Exact `name = ?` | "rahul verma" (and even "Rahul Verma") → `[]` | `LOWER(TRIM(name)) = LOWER(TRIM(?))`; maybe `LIKE` fallback for partial matches |
| Not found returns `[]` | Model says "no such customer" with confidence, can't tell miss from bug | Explicit `{"error": "customer_not_found", "hint": "ask user to confirm spelling"}` |
| Returns bare tuples | Model guesses which field is which | List of dicts with named keys |
| Multiple matches not handled | Two "Priya"s → model picks one silently | Return all with a note "multiple matches, ask which one" |
| Description "Find a customer." | Model doesn't know match rules or what comes back | Say: case-insensitive full-name match, returns id/name/email/city, use id for other tools |

### get_customer_orders
| Problem | Fix |
|---|---|
| `customer_id` typed `string` in schema, integer in DB (works in SQLite by luck; fails in Postgres) | `integer` |
| No cap — Asha returns 131 rows | `limit` param (default 20, max 50) + `truncated` + total count |
| Raw mixed-case status | Normalize `LOWER(status)` in output |
| Tuples | Dicts |
| Description "Get orders." | Say what, for whom, ordering, cap |

### get_order_total
| Problem | Symptom | Fix |
|---|---|---|
| `fetchone()[0]` on missing order | 9999 → `TypeError` crash | Check row is None → `order_not_found` error |
| `total` unlabeled, in **paise** | Model says "₹21,89,600" — 100× wrong | Return `total_rupees` (and/or `total_paise`) with explicit unit in the key name |
| Fetches status then throws it away | Model doesn't know order 5 is **cancelled** | Include `status` in the output |

### sales_report
| Problem | Symptom | Fix |
|---|---|---|
| Schema `start`/`end` vs handler `start_date`/`end_date` | Always crashes (`unexpected keyword argument`) | Make names match (single source of truth) |
| No date format in schema/description | "January 2026" → 0 orders, None revenue (silent wrong) | Describe `YYYY-MM-DD`, add `"pattern"` or `"format": "date"`, validate in handler → error with example |
| Counts cancelled/refunded as revenue | 41 orders / ₹4,69,079 instead of 30 / ₹3,59,592 | Exclude them (business rule), say so in output (`"excludes": [...]`) |
| `revenue` unlabeled paise | 100× wrong | `revenue_rupees` |
| `None` when no data | Model may say "None" | Return 0 + `"orders": 0` explicitly |
| Inclusive end date ambiguity | Docs: is `end_date` inclusive? | State it in description |

### issue_refund — the dangerous one
| Problem | Symptom | Fix |
|---|---|---|
| No existence check | Refunds order 9999 (inserts row for nonexistent order) | Validate order exists |
| No status check | Refunds **cancelled** order 5, re-refunds **already refunded** order 2 | Allow only delivered/shipped; error otherwise with current status |
| `amount` unit ambiguous (`number`) | Model sends 21896 (rupees) into a paise column, or 2189600 into what it thinks is rupees | Name it `amount_rupees` or `amount_paise`, integer, `minimum` > 0 |
| No max check | Can refund more than the order total | `amount ≤ order total − already refunded` |
| **Not idempotent** | "do it again, I don't think it worked" → second refund row → double refund | Check existing refund for order (or idempotency key) → return the existing refund instead of creating a new one |
| No confirmation | Irreversible money action on first mention | Two-step: `preview_refund` → user confirms → `issue_refund(confirm=True)`; or system-prompt policy "always confirm amount with the user first" (weaker) |
| Returns "Refund issued." | No refund id, amount, new status → model can't report or verify | Return `{"refund_id", "order_id", "amount_rupees", "new_status"}` |
| Description "Refund an order." | Model doesn't know rules/limits | State eligibility, units, idempotency, that it's irreversible |

### System prompt
- No business rules: revenue excludes cancelled/refunded; money is paise internally; confirm before refunds; don't guess customer identity.

## Talking points
- Fix in the lowest layer you control: handler > schema/description > prompt.
- Strict mode fixes shape (L2/L3, `start` vs `start_date` at the schema level) but NOT semantics (paise, status, idempotency).
- Every tool output: named fields, explicit units, explicit not-found, truncation flagged.
- Write tools: validate → check state → idempotent → confirm → return a receipt.
