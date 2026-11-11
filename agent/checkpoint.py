"""The human checkpoint: no write happens until a person has seen it and said yes.

The `approval` node sits between the model and the tools. When the model asks for a
write tool, the node pauses the graph with interrupt() and hands the caller a
description of the write. The run continues only when the caller resumes it:

    graph.invoke(Command(resume={"approved": True}), config)
    graph.invoke(Command(resume={"approved": False, "reason": "..."}), config)

LangGraph re-runs this node from its first line on resume, so nothing before
interrupt() may change anything: the preview below only reads.
"""

import time
from pathlib import Path
from typing import Literal

from langchain.messages import ToolMessage
from langgraph.types import Command, interrupt

from agent.calls import write_log
from agent.state import AgentState
from agent.tools import WRITE_TOOLS
from sandbox.runner import load_config


def preview(work: Path, tool_call: dict) -> dict:
    """Describe a write for the human: the tool, its arguments, and what would change."""
    shown = {"tool": tool_call["name"], "args": tool_call["args"]}
    try:
        config = load_config(work, tool_call["args"]["job_id"])
        if tool_call["name"] == "update_job_config":
            shown["diff"] = {
                key: {"old": config.get(key), "new": new}
                for key, new in tool_call["args"]["changes"].items()
            }
        else:
            shown["config_that_will_run"] = config
    except Exception:  # odd arguments: still show the raw request, the tool will reject it
        shown["note"] = "could not build a preview from these arguments"
    return shown


def make_approval(work: Path, log_path: Path | None = None):
    """Create the approval node for one sandbox folder."""

    def approval(state: AgentState) -> Command[Literal["tools", "llm"]]:
        calls = state["messages"][-1].tool_calls
        writes = [preview(work, call) for call in calls if call["name"] in WRITE_TOOLS]
        decision = interrupt({"question": "Approve this write?", "writes": writes})

        # Only an explicit yes lets the write through. Anything else is a no.
        if isinstance(decision, dict) and decision.get("approved") is True:
            return Command(goto="tools")

        reason = decision.get("reason") if isinstance(decision, dict) else None
        text = (
            f"REJECTED by the human reviewer. Reason: {reason or 'none given'}. Nothing was "
            "executed. Do not repeat this call. Follow the reason if it asks for a different "
            "change; otherwise stop and report."
        )
        started = time.perf_counter()
        answers = []
        for call in calls:  # every requested call needs an answer, executed or not
            write_log(log_path, call, text, "rejected", started)
            answers.append(ToolMessage(content=text, tool_call_id=call["id"], name=call["name"], status="error"))
        return Command(goto="llm", update={"messages": answers})

    return approval
