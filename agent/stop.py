"""The stopping condition. Written before the agent, as the brief asks.

Three independent limits (see DECISIONS.md D6):
1. max_steps   - graceful: after this many model calls the run goes to `finalize`.
2. max_tokens  - graceful: once this many tokens are used the run goes to `finalize`.
3. recursion_limit - hard: LangGraph raises GraphRecursionError. It only fires if
   the two graceful rules are broken by a bug, so the loop can never run forever.
"""

from dataclasses import dataclass

from agent.state import AgentState

# One loop turn uses at most 3 graph nodes: llm -> approval -> tools.
NODES_PER_STEP = 3


@dataclass(frozen=True)
class Limits:
    max_steps: int = 12
    max_tokens: int = 40_000


def stop_reason(state: AgentState, limits: Limits) -> str | None:
    """Return why the run must stop now, or None if it may continue.

    Called right after every model call, by the router and by `finalize`.
    """
    last_message = state["messages"][-1]
    if not getattr(last_message, "tool_calls", None):
        return "done"  # the model asked for no tool: it considers the task finished
    if state.get("steps", 0) >= limits.max_steps:
        return "max_steps"
    if state.get("tokens_used", 0) >= limits.max_tokens:
        return "budget"
    return None


def hard_recursion_limit(limits: Limits) -> int:
    """LangGraph recursion_limit: just above what a run obeying max_steps can need."""
    return limits.max_steps * NODES_PER_STEP + 5
