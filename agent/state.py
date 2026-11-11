"""The state that flows through the graph. Every node reads it and returns updates to it."""

from typing import Annotated, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Conversation so far. add_messages appends new messages instead of replacing the list.
    messages: Annotated[list[AnyMessage], add_messages]
    # Number of model calls made so far. One step = one model call.
    steps: int
    # Total tokens (input + output) reported by the model so far.
    tokens_used: int
    # Why the run ended: "done", "max_steps" or "budget". None while running.
    stop_reason: str | None
