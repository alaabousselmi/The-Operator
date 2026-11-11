"""How tool calls are executed: one place for error text and for the call log.

We use two hooks of LangGraph's ToolNode:
- handle_tool_errors: turns ANY exception into one clear line the model can act on.
- wrap_tool_call:     runs around every call; we use it to log input, output and time.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from agent.tools import ToolError


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


def make_tool_node(tools: list, log_path: Path | None = None) -> ToolNode:
    """Build the graph node that runs tools, with error formatting and call logging."""

    def log_call(request, execute):
        started = time.perf_counter()
        result = execute(request)  # errors are already turned into a message here
        if log_path is not None:
            entry = {
                "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "tool": request.tool_call["name"],
                "input": request.tool_call["args"],
                "output": getattr(result, "content", str(result)),
                "status": getattr(result, "status", "success"),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            with log_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry) + "\n")
        return result

    return ToolNode(tools, handle_tool_errors=format_error, wrap_tool_call=log_call)
