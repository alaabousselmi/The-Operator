"""Run the agent once, asking the `approve` function before every write.

Used by the command line (a person answers) and by the eval (a policy answers).
"""

import uuid
from pathlib import Path
from typing import Callable

from langchain.messages import HumanMessage
from langgraph.types import Command

from agent.graph import build_graph, run_config
from agent.prompts import TASK
from agent.stop import Limits
from sandbox.paths import WORK


def run_agent(model, approve: Callable[[dict], dict], work: Path = WORK, limits: Limits = Limits(),
              checkpointer=None, tool_failures: dict | None = None, on_message=None) -> dict:
    """Run until the agent stops. Return the final state (messages, steps, stop_reason...).

    approve(request) receives {"question", "writes"} and returns
    {"approved": True} or {"approved": False, "reason": "..."}.
    on_message(message) is called for every new message, to show progress.
    """
    graph = build_graph(model, work, limits, checkpointer, tool_failures=tool_failures)
    config = run_config(limits, thread_id=str(uuid.uuid4()))
    shown = 0
    step_input = {"messages": [HumanMessage(TASK)]}
    while True:
        state = graph.invoke(step_input, config)
        for message in state["messages"][shown:]:
            if on_message:
                on_message(message)
        shown = len(state["messages"])
        if "__interrupt__" not in state:
            return state
        request = state["__interrupt__"][0].value  # the pending write, from the approval node
        step_input = Command(resume=approve(request))
