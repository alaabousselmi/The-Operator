"""How tool calls are executed: one place for error text and for the call log.

We use two hooks of LangGraph's ToolNode:
- handle_tool_errors: turns ANY exception into one clear line the model can act on.
- wrap_tool_call:     runs around every call; we use it to log input, output and time.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain.messages import ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from agent.tools import ToolError

# Failures the eval can inject to test recovery (the tool is then NOT executed).
INJECTED_FAILURES = {
    "unavailable": "ERROR E_TOOL_UNAVAILABLE: the pipeline service did not respond. Retry the same call once.",
    "timeout": "ERROR E_TOOL_TIMEOUT: the tool gave no answer within 30 seconds. Retry the same call once.",
    "empty": "",  # the tool answers, but with nothing
}


def format_error(error: Exception) -> str:
    """The text the model sees when a tool call fails. Never a stack trace."""
    if isinstance(error, ToolError):
        return str(error)
    if isinstance(error, ToolInvocationError):  # arguments rejected by the schema
        problems = "; ".join(
            f"{'.'.join(str(part) for part in detail['loc']) or 'arguments'}: {detail['msg']}"
            for detail in error.source.errors()
        )
        return f"ERROR E_BAD_ARGUMENTS: {problems}. Fix the arguments and call the tool again."
    return (
        f"ERROR E_TOOL_FAILED: the tool failed unexpectedly ({type(error).__name__}). "
        "Retry once; if it fails again, stop and report the problem."
    )


def write_log(log_path: Path | None, tool_call: dict, output: str, status: str, started: float) -> None:
    """Append one tool call to the log: when, which tool, input, output, how long."""
    if log_path is None:
        return
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "tool": tool_call["name"],
        "input": tool_call["args"],
        "output": output,
        "status": status,  # success, error, rejected (by the human) or injected_failure
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry) + "\n")


def make_tool_node(tools: list, log_path: Path | None = None, tool_failures: dict | None = None) -> ToolNode:
    """Build the graph node that runs tools, with error formatting and call logging.

    tool_failures: eval only. {"tool_name": ["unavailable", ...]} makes the next calls
    to that tool fail, one list item per call, without running the tool.
    """
    failures = {name: list(kinds) for name, kinds in (tool_failures or {}).items()}

    def log_call(request, execute):
        started = time.perf_counter()
        call = request.tool_call
        if failures.get(call["name"]):
            text = INJECTED_FAILURES[failures[call["name"]].pop(0)]
            write_log(log_path, call, text, "injected_failure", started)
            return ToolMessage(content=text, tool_call_id=call["id"], name=call["name"], status="error")
        result = execute(request)  # errors are already turned into a message here
        write_log(log_path, call, getattr(result, "content", str(result)), getattr(result, "status", "success"), started)
        return result

    return ToolNode(tools, handle_tool_errors=format_error, wrap_tool_call=log_call)
