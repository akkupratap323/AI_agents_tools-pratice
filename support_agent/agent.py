"""
agent.py - the agent loop (Chat Completions format).

run_agent(messages) -> final answer text. It mutates `messages` in place, so
the caller (cli.py) keeps the full history for follow-up questions.

Invariants this loop guarantees:
  1. the assistant message is appended BEFORE its tool results
     (a tool message must answer a preceding assistant tool_call - else HTTP 400)
  2. EVERY tool_call id gets exactly one tool message, even when the tool fails
     (parallel calls included)
  3. bounded by MAX_TURNS - a model that never stops can't loop forever
  4. every turn is logged: finish_reason, tokens, latency, each call and result
"""

import time

from . import llm
from .config import LOG_RESULT_CHARS, MAX_TURNS, MODEL
from .dispatcher import dispatch
from .tools import TOOLS


def run_agent(messages):
    for turn in range(1, MAX_TURNS + 1):
        t0 = time.monotonic()
        resp = llm.client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        choice = resp.choices[0]
        msg = choice.message
        print(f"\n[turn {turn}] finish_reason={choice.finish_reason} "
              f"tokens(in={resp.usage.prompt_tokens}, out={resp.usage.completion_tokens}) "
              f"{time.monotonic() - t0:.1f}s")

        messages.append(msg)                                  # invariant 1

        if msg.content:
            print(f"  model: {msg.content.strip()[:300]}")

        if not msg.tool_calls:                                # no tools -> final answer
            if choice.finish_reason == "length":
                return (msg.content or "") + "\n\n(answer cut off: output token limit reached)"
            return msg.content or "(empty answer)"

        for tc in msg.tool_calls:                             # invariant 2
            t1 = time.monotonic()
            content, is_error = dispatch(tc.function.name, tc.function.arguments)
            print(f"  -> {tc.function.name}({tc.function.arguments})")
            print(f"  <- [{'ERROR' if is_error else 'ok'} {1000 * (time.monotonic() - t1):.0f}ms] "
                  f"{content[:LOG_RESULT_CHARS]}")
            # Chat Completions has no is_error field: the error is inside content.
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

    return f"(stopped: no final answer after {MAX_TURNS} turns)"   # invariant 3
