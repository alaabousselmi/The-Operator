"""The stopping condition. Written before the agent, as the brief asks.

Four independent limits (see DECISIONS.md D6):
1. max_steps   - graceful: after this many model calls the run goes to `finalize`.
2. max_tokens  - graceful: once this many tokens are used the run goes to `finalize`.
3. max_repeats - graceful: the model may ask for the exact same tool call (same tool,
   same arguments) at most this many times; one more and the run stops as a "loop".
   This is also the retry limit: a failed call can be retried max_repeats - 1 times.
4. recursion_limit - hard: LangGraph raises GraphRecursionError. It only fires if
   the graceful rules are broken by a bug, so the loop can never run forever.
"""

import json
from dataclasses import dataclass

from agent.state import AgentState

# One loop turn uses at most 3 graph nodes: llm -> approval -> tools.
NODES_PER_STEP = 3


@dataclass(frozen=True)
class Limits:
    max_steps: int = 12
    max_tokens: int = 40_000
    max_repeats: int = 3


def call_key(tool_call: dict) -> str:
    """A tool call as text, so two identical calls compare equal."""
    return tool_call["name"] + json.dumps(tool_call["args"], sort_keys=True)


def stop_reason(state: AgentState, limits: Limits) -> str | None:
    """Return why the run must stop now, or None if it may continue.

    Called right after every model call, by the router and by `finalize`.
    """
    last_message = state["messages"][-1]
    pending = getattr(last_message, "tool_calls", None)
    if not pending:
        return "done"  # the model asked for no tool: it considers the task finished
    if state.get("steps", 0) >= limits.max_steps:
        return "max_steps"
    if state.get("tokens_used", 0) >= limits.max_tokens:
        return "budget"
    asked_so_far = [
        call_key(call)
        for message in state["messages"]
        for call in getattr(message, "tool_calls", None) or []
    ]
    if any(asked_so_far.count(call_key(call)) > limits.max_repeats for call in pending):
        return "loop"
    return None


def hard_recursion_limit(limits: Limits) -> int:
    """LangGraph recursion_limit: just above what a run obeying max_steps can need."""
    return limits.max_steps * NODES_PER_STEP + 5
