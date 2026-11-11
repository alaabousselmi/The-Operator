"""The agent loop as a LangGraph StateGraph (single agent, ReAct style).

                 +--> finalize --> END        (stop rule fired, or the model is done)
    START --> llm +--> approval --> tools --+  (the model asked for a write)
               ^  |        +--> llm            (the human said no)
               |  +--> tools ---------------+  (the model asked for a read)
               +----------------------------+
"""

from pathlib import Path

from langchain.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.calls import make_tool_node
from agent.checkpoint import make_approval
from agent.prompts import model_input
from agent.state import AgentState
from agent.stop import Limits, hard_recursion_limit, stop_reason
from agent.tools import WRITE_TOOLS, make_tools
from sandbox.paths import WORK


def executed_writes(messages: list) -> list[str]:
    """The write calls that really ran, e.g. ['update_job_config', 'rerun_job']."""
    return [m.name for m in messages if m.type == "tool" and m.name in WRITE_TOOLS and m.status == "success"]


def build_graph(model, work: Path = WORK, limits: Limits = Limits(), checkpointer=None,
                tools: list | None = None, tool_failures: dict | None = None):
    """Build and compile the agent graph.

    model: a chat model. work: the sandbox folder. checkpointer: where paused runs are
    saved (memory by default). tools / tool_failures: overrides used only by tests and eval.
    """
    tools = make_tools(work) if tools is None else tools
    log_path = work / "tool_calls.jsonl"
    model_with_tools = model.bind_tools(tools)

    def llm(state: AgentState) -> dict:
        response = model_with_tools.invoke(model_input(state["messages"]))
        usage = response.usage_metadata or {}  # some providers return no usage
        return {
            "messages": [response],
            "steps": state.get("steps", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + usage.get("total_tokens", 0),
        }

    def router(state: AgentState) -> str:
        if stop_reason(state, limits) is not None:
            return "finalize"
        wants_write = any(call["name"] in WRITE_TOOLS for call in state["messages"][-1].tool_calls)
        return "approval" if wants_write else "tools"

    def finalize(state: AgentState) -> dict:
        reason = stop_reason(state, limits)
        if reason == "done":
            return {"stop_reason": reason}
        # Stopped by a limit: the last tool request is NOT executed. Say what was done.
        note = (
            f"Stopped by the {reason} limit after {state.get('steps', 0)} steps and "
            f"{state.get('tokens_used', 0)} tokens. The task may be incomplete. "
            f"Writes executed so far: {executed_writes(state['messages']) or 'none'}. "
            "Old configs are kept in the sandbox backups folder."
        )
        return {"stop_reason": reason, "messages": [AIMessage(content=note)]}

    builder = StateGraph(AgentState)
    builder.add_node("llm", llm)
    builder.add_node("approval", make_approval(work, log_path))
    builder.add_node("tools", make_tool_node(tools, log_path, tool_failures))
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", router, ["tools", "approval", "finalize"])
    builder.add_edge("tools", "llm")
    builder.add_edge("finalize", END)
    # A checkpointer is always present: without one the approval pause cannot work.
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def run_config(limits: Limits, thread_id: str = "default") -> dict:
    """Config for graph.invoke: sets the hard recursion limit and the thread id."""
    return {
        "recursion_limit": hard_recursion_limit(limits),
        "configurable": {"thread_id": thread_id},
    }
