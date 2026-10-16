"""
cli.py - the chat REPL.

Owns the conversation history. One `messages` list lives across questions, so
follow-ups ("and what about order 7?") work. /reset starts fresh.

If the API call itself fails (auth, network, a 400 from a malformed history),
the history is rolled back to before the question, so the next question does
not inherit a half-finished turn (e.g. tool_calls with no results).
"""

import os

from . import dispatcher
from .agent import run_agent
from .config import DB_PATH, MODEL
from .prompts import SYSTEM


def main():
    messages = [{"role": "system", "content": SYSTEM}]
    print(f"Support agent ({MODEL}, SQLite: {os.path.basename(DB_PATH)}). /reset clears memory, /exit quits.\n")

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
            messages = [{"role": "system", "content": SYSTEM}]
            dispatcher.reset()               # forget repeated-failure counts too
            print("(conversation cleared)\n")
            continue

        messages.append({"role": "user", "content": question})
        history_len = len(messages)
        try:
            answer = run_agent(messages)
        except Exception as e:
            print(f"\n!! API error: {type(e).__name__}: {e}")
            del messages[history_len - 1:]    # roll back to before this question
            continue
        print(f"\nagent: {answer}\n")
