"""Run the agent from the command line.

    python -m agent.cli --scenario bad_date_format      break a job, then repair it
    python -m agent.cli --no-seed                       use the sandbox as it is now

The agent prints each step. Before every write it shows the change and waits for y/n.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.run import run_agent
from agent.stop import Limits
from sandbox.faults import FAULTS
from sandbox.paths import SANDBOX_DIR, WORK
from sandbox.seed import seed

DEFAULT_MODEL = "groq:openai/gpt-oss-120b"


def show(message) -> None:
    """Print one message of the run in a readable form."""
    if message.type == "ai":
        for call in message.tool_calls:
            print(f"\n[agent -> tool] {call['name']} {json.dumps(call['args'])}")
        if message.content:
            print(f"\n[agent] {message.content}")
    elif message.type == "tool":
        print(f"[tool result] {str(message.content)[:600]}")


def ask_human(request: dict) -> dict:
    """The human checkpoint: show the write and wait for a yes."""
    print("\n" + "=" * 70 + "\nAPPROVAL NEEDED - the agent wants to write:")
    print(json.dumps(request["writes"], indent=2))
    if input("Approve? [y/N] ").strip().lower() == "y":
        return {"approved": True}
    return {"approved": False, "reason": input("Reason (shown to the agent): ").strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Data pipeline repair agent")
    parser.add_argument("--scenario", choices=sorted(FAULTS), default="bad_date_format", help="fault to seed")
    parser.add_argument("--job", default="load_orders", help="job to break")
    parser.add_argument("--no-seed", action="store_true", help="do not reset the sandbox first")
    parser.add_argument("--auto-approve", action="store_true", help="approve every write (eval only)")
    args = parser.parse_args()

    load_dotenv()
    # .env may name the keys GROQ_API_KEY_1, _2, ...: use the first one as the default key.
    os.environ.setdefault("GROQ_API_KEY", os.environ.get("GROQ_API_KEY_1", ""))
    if not args.no_seed:
        failed = seed(args.scenario, args.job)
        print(f"Sandbox seeded: {failed}")
    model = init_chat_model(os.environ.get("OPERATOR_MODEL", DEFAULT_MODEL), temperature=0)
    approve = (lambda request: {"approved": True}) if args.auto_approve else ask_human

    # Paused runs are saved in SQLite, outside .work so a sandbox reset cannot lock it.
    with closing(sqlite3.connect(SANDBOX_DIR / "checkpoints.db", check_same_thread=False)) as connection:
        state = run_agent(model, approve, WORK, Limits(), SqliteSaver(connection), on_message=show)
    print(f"\nStopped: {state['stop_reason']} | steps: {state['steps']} | tokens: {state['tokens_used']}")


if __name__ == "__main__":
    main()
