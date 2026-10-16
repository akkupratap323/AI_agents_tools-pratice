"""
================================================================================
 agent_anthropic.py  -  support agent on the ANTHROPIC MESSAGES API
================================================================================

 Same hardened tools as drill_agent.py (via support_tools.py), on Claude,
 against SQLite or Postgres.

 Setup:   pip install anthropic
          set ANTHROPIC_API_KEY in .env (or log in with `ant auth login`)
          Postgres only: see db_postgres.py (docker + make_pg.py)
 Run:     python agent_anthropic.py --db sqlite
          python agent_anthropic.py --db postgres
 Model:   env ANTHROPIC_MODEL, default claude-opus-5-5

 ------------------------------------------------------------------------------
 ANTHROPIC FORMAT - what differs from Chat Completions (cheat sheet)
 ------------------------------------------------------------------------------
   tools           {name, description, input_schema, strict}   (no "function" wrapper)
   system prompt   top-level `system=`, NOT a message
   max_tokens      REQUIRED on every request
   model asks      response.content has blocks of type "tool_use" {id, name, input}
   input           already a dict (no json.loads needed)
   save the turn   messages.append({"role": "assistant", "content": response.content})
                   -> the WHOLE content list (text + thinking + tool_use blocks)
   send results    ONE user message containing ALL tool_result blocks:
                   {"type": "tool_result", "tool_use_id": <id>, "content": str, "is_error": bool}
                   Splitting them across messages teaches the model to stop
                   making parallel calls. Never drop one - failures get is_error.
   stop_reason     tool_use   -> run tools, loop
                   end_turn   -> final answer
                   max_tokens -> output was cut off (a tool_use may be incomplete)
                   pause_turn -> server-side pause; resend to continue
                   refusal    -> safety decline; check stop_details
================================================================================
"""

import argparse
import os
import time

import anthropic
from dotenv import load_dotenv

from support_tools import SYSTEM_PROMPT, SupportTools, open_database, to_anthropic

load_dotenv()

# ═════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════════════════

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_TOKENS = 16000          # required by the API; generous so answers aren't cut off
EFFORT = "medium"           # Opus 5.5 always thinks; effort is the depth/cost knob (its default is medium)
MAX_TURNS = 10
LOG_RESULT_CHARS = 400

# Refusal fallback: if a safety classifier declines, the API re-runs the same
# request on a fallback model inside the same call ("default" routes by refusal
# category). Opt-in via a beta header; set False to use the plain endpoint.
USE_REFUSAL_FALLBACK = True

TOOLS = to_anthropic(strict=True)   # strict: inputs always match the schema, names always valid

client = anthropic.Anthropic(max_retries=2, timeout=120.0)   # SDK retries 429/5xx/connection errors


def create_message(messages):
    params = dict(model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT, tools=TOOLS,
                  messages=messages, output_config={"effort": EFFORT})
    if USE_REFUSAL_FALLBACK:
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                           fallbacks="default", **params)
    return client.messages.create(**params)


def text_of(content):
    return "".join(b.text for b in content if b.type == "text").strip()


# ═════════════════════════════════════════════════════════════════════════════
# AGENT LOOP
#   Invariants: assistant turn appended (whole content) before its results;
#   every tool_use id answered exactly once, all in ONE user message;
#   bounded by MAX_TURNS; every stop_reason handled explicitly.
# ═════════════════════════════════════════════════════════════════════════════




def run_agent(messages, tools):
    for turn in range(1, MAX_TURNS + 1):
        t0 = time.monotonic()
        resp = create_message(messages)
        print(f"\n[turn {turn}] stop_reason={resp.stop_reason} model={resp.model} "
              f"tokens(in={resp.usage.input_tokens}, out={resp.usage.output_tokens}) "
              f"{time.monotonic() - t0:.1f}s")

        if resp.stop_reason == "refusal":
            # Don't append: a refused turn is not useful history.
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            return f"(the model declined this request; category={category})"

        if resp.stop_reason == "max_tokens":
            # The output was cut off. A tool_use block may be incomplete, and
            # appending a tool_use without its tool_result would make the NEXT
            # request a 400. So we don't append; we report the truncation.
            return (text_of(resp.content) + "\n\n(answer cut off at max_tokens)").strip()

        messages.append({"role": "assistant", "content": resp.content})   # whole content list

        said = text_of(resp.content)
        if said:
            print(f"  model: {said[:300]}")

        if resp.stop_reason == "pause_turn":
            continue          # server paused a long turn; resending the history resumes it

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            return said or "(empty answer)"                               # end_turn / stop_sequence

        results = []
        for block in tool_uses:                                           # parallel calls: answer all
            t1 = time.monotonic()
            content, is_error = tools.execute(block.name, block.input)    # input is already a dict
            print(f"  -> {block.name}({block.input})")
            print(f"  <- [{'ERROR' if is_error else 'ok'} {1000 * (time.monotonic() - t1):.0f}ms] "
                  f"{content[:LOG_RESULT_CHARS]}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})            # ONE message, ALL results

    return f"(stopped: no final answer after {MAX_TURNS} turns)"


# ═════════════════════════════════════════════════════════════════════════════
# CHAT REPL
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Support agent on the Anthropic Messages API")
    parser.add_argument("--db", choices=["sqlite", "postgres"], default="sqlite")
    args = parser.parse_args()

    tools = SupportTools(open_database(args.db))
    messages = []   # Anthropic: the system prompt is NOT a message
    print(f"Support agent (Anthropic {MODEL}, {args.db}: {tools.db.path}). /reset, /exit\n")

    while True:
        try:
            question = input("you: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
            break
        if not question:
            continue
        if question == "/exit":
            break
        if question == "/reset":
            messages = []
            tools.reset()          # forget repeated-failure counts too
            print("(conversation cleared)\n")
            continue

        messages.append({"role": "user", "content": question})
        history_len = len(messages)
        try:
            answer = run_agent(messages, tools)
        except anthropic.BadRequestError as e:
            # 400 = OUR request is malformed (usually the message history). Retrying won't help.
            print(f"\n!! 400 bad request: {e.message}")
            del messages[history_len - 1:]
            continue
        except anthropic.AuthenticationError:
            print("\n!! invalid API key (ANTHROPIC_API_KEY)")
            break
        except anthropic.RateLimitError:
            print("\n!! rate limited even after SDK retries - wait and ask again")
            del messages[history_len - 1:]
            continue
        except anthropic.APIStatusError as e:
            print(f"\n!! API error {e.status_code}: {e.message}")
            del messages[history_len - 1:]
            continue
        except anthropic.APIConnectionError:
            print("\n!! network error - check the connection")
            del messages[history_len - 1:]
            continue
        print(f"\nagent: {answer}\n")


if __name__ == "__main__":
    main()
