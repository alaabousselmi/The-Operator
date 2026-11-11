"""The agent loop as a LangGraph StateGraph.

    START -> llm -> (router) -> tools -> llm -> ... -> finalize -> END

Phase 4 adds the human `approval` node between the router and `tools`.
"""

from langchain.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.state import AgentState
from agent.stop import Limits, hard_recursion_limit, stop_reason


def build_graph(model, tools, limits: Limits = Limits(), checkpointer=None):
    """Build and compile the agent graph for a chat model and a list of tools."""
    model_with_tools = model.bind_tools(tools)

    def llm(state: AgentState) -> dict:
        response = model_with_tools.invoke(state["messages"])
        usage = response.usage_metadata or {}  # some providers return no usage
        return {
            "messages": [response],
            "steps": state.get("steps", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + usage.get("total_tokens", 0),
        }

    def router(state: AgentState) -> str:
        return "tools" if stop_reason(state, limits) is None else "finalize"

    def finalize(state: AgentState) -> dict:
        reason = stop_reason(state, limits)
        if reason == "done":
            return {"stop_reason": reason}
        # Stopped by a limit: the last tool request is NOT executed. Say so plainly.
        note = (
            f"Stopped by the {reason} limit after {state.get('steps', 0)} steps and "
            f"{state.get('tokens_used', 0)} tokens. The task may be incomplete."
        )
        return {"stop_reason": reason, "messages": [AIMessage(content=note)]}

    builder = StateGraph(AgentState)
    builder.add_node("llm", llm)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", router, ["tools", "finalize"])
    builder.add_edge("tools", "llm")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def run_config(limits: Limits, thread_id: str = "default") -> dict:
    """Config for graph.invoke: sets the hard recursion limit and the thread id."""
    return {
        "recursion_limit": hard_recursion_limit(limits),
        "configurable": {"thread_id": thread_id},
    }
