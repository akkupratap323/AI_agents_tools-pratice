"""
================================================================================
 agent_openai_responses.py  -  support agent on the OPENAI RESPONSES API
================================================================================

 Same hardened tools (support_tools.py), on OpenAI's newer Responses API,
 against SQLite or Postgres.

 Setup:   pip install openai
          set OPENAI_API_KEY in .env   (DeepSeek does NOT support this API -
                                         it only speaks Chat Completions; use
                                         drill_agent.py for DeepSeek)
 Run:     python multi_provider/agent_openai_responses.py --db sqlite
          python multi_provider/agent_openai_responses.py --db postgres
 Model:   env OPENAI_MODEL (default below is the one used in OpenAI's own
          function-calling guide; change it to any model your key can use)

 ------------------------------------------------------------------------------
 RESPONSES FORMAT - what differs from Chat Completions and Anthropic
 ------------------------------------------------------------------------------
   tools           FLAT {type:"function", name, description, parameters, strict}
   system prompt   `instructions=` on each request
   history         a list called `input`; append EVERYTHING in response.output
                   (reasoning items, function_call items, messages) every turn
   model asks      items in response.output with type == "function_call"
                   fields: name, arguments (JSON STRING), call_id
   send results    one input item per call:
                   {"type": "function_call_output", "call_id": <call_id>, "output": str}
                   (no is_error flag - the error lives in the output text)
   final text      response.output_text
   cut off         response.status == "incomplete"
                   (incomplete_details.reason == "max_output_tokens")
================================================================================
"""

import argparse
import os
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI

from support_tools import SYSTEM_PROMPT, SupportTools, open_database, to_responses

load_dotenv()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-astra")
MAX_TURNS = 10
LOG_RESULT_CHARS = 400

TOOLS = to_responses()    # strict=False: see to_responses() for why

client = OpenAI(max_retries=2, timeout=120.0)   # reads OPENAI_API_KEY


# ═════════════════════════════════════════════════════════════════════════════
# AGENT LOOP
#   Invariants: every output item is appended to `input` before the results;
#   every call_id gets exactly one function_call_output, even on error;
#   bounded by MAX_TURNS.
# ═════════════════════════════════════════════════════════════════════════════

def run_agent(input_items, tools):
    for turn in range(1, MAX_TURNS + 1):
        t0 = time.monotonic()
        resp = client.responses.create(model=MODEL, instructions=SYSTEM_PROMPT,
                                       tools=TOOLS, input=input_items)
        usage = resp.usage
        print(f"\n[turn {turn}] status={resp.status} "
              f"tokens(in={usage.input_tokens}, out={usage.output_tokens}) "
              f"{time.monotonic() - t0:.1f}s")

        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", None)
            # A cut-off function_call would have no output -> next request fails.
            # Don't append; report.
            return (resp.output_text + f"\n\n(answer incomplete: {reason})").strip()

        input_items += resp.output              # the model's turn, ALL items, first

        calls = [item for item in resp.output if item.type == "function_call"]
        if resp.output_text and calls:
            print(f"  model: {resp.output_text.strip()[:300]}")
        if not calls:
            return resp.output_text or "(empty answer)"

        for call in calls:                      # answer EVERY call_id
            t1 = time.monotonic()
            output, is_error = tools.execute_json(call.name, call.arguments)   # arguments: JSON string
            print(f"  -> {call.name}({call.arguments})")
            print(f"  <- [{'ERROR' if is_error else 'ok'} {1000 * (time.monotonic() - t1):.0f}ms] "
                  f"{output[:LOG_RESULT_CHARS]}")
            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": output})

    return f"(stopped: no final answer after {MAX_TURNS} turns)"


# ═════════════════════════════════════════════════════════════════════════════
# CHAT REPL
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Support agent on the OpenAI Responses API")
    parser.add_argument("--db", choices=["sqlite", "postgres"], default="sqlite")
    args = parser.parse_args()

    tools = SupportTools(open_database(args.db))
    input_items = []
    print(f"Support agent (OpenAI Responses {MODEL}, {args.db}: {tools.db.path}). /reset, /exit\n")

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
            input_items = []
            tools.reset()          # forget repeated-failure counts too
            print("(conversation cleared)\n")
            continue

        input_items.append({"role": "user", "content": question})
        history_len = len(input_items)
        try:
            answer = run_agent(input_items, tools)
        except openai.BadRequestError as e:
            print(f"\n!! 400 bad request (usually malformed history): {e}")
            del input_items[history_len - 1:]
            continue
        except openai.AuthenticationError:
            print("\n!! invalid API key (OPENAI_API_KEY)")
            break
        except openai.APIStatusError as e:
            print(f"\n!! API error {e.status_code}: {e}")
            del input_items[history_len - 1:]
            continue
        except openai.APIConnectionError:
            print("\n!! network error - check the connection")
            del input_items[history_len - 1:]
            continue
        print(f"\nagent: {answer}\n")


if __name__ == "__main__":
    main()
