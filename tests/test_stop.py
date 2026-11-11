"""Proof that the agent loop cannot run forever (Tasks T1.4).

The fake model asks for a tool on every turn and never finishes by itself,
so only the stop rule can end these runs.
"""

import pytest
from langchain.messages import HumanMessage
from langchain.tools import tool
from langgraph.errors import GraphRecursionError

from agent.graph import build_graph, run_config
from agent.stop import Limits
from eval.fake_model import FakeModel

tool_runs = []


@tool
def ping() -> str:
    """Do nothing and return ok."""
    tool_runs.append(1)
    return "ok"


def run(model, limits, config=None):
    tool_runs.clear()
    graph = build_graph(model, [ping], limits)
    start = {"messages": [HumanMessage("repair the job")]}
    return graph.invoke(start, config or run_config(limits))


def forever_model(**kwargs):
    return FakeModel(script=[[("ping", {})]], loop_forever=True, **kwargs)


def test_normal_run_stops_when_model_is_done():
    model = FakeModel(script=[[("ping", {})], [("ping", {})]])
    result = run(model, Limits(max_steps=10))
    assert result["stop_reason"] == "done"
    assert result["steps"] == 3  # two tool turns + one final answer
    assert len(tool_runs) == 2


@pytest.mark.parametrize("max_steps", [1, 2, 5, 12, 30])
def test_looping_model_is_stopped_by_max_steps(max_steps):
    model = forever_model()
    result = run(model, Limits(max_steps=max_steps, max_tokens=10**9))
    assert result["stop_reason"] == "max_steps"
    assert model.calls == max_steps  # never one call more than allowed
    assert result["steps"] == max_steps
    assert len(tool_runs) == max_steps - 1  # the last tool request is not executed
    assert "max_steps" in result["messages"][-1].content


def test_looping_model_is_stopped_by_token_budget():
    model = forever_model(tokens_per_call=1_000)
    result = run(model, Limits(max_steps=10**6, max_tokens=3_500), {"recursion_limit": 100})
    assert result["stop_reason"] == "budget"
    assert model.calls == 4  # 4 x 1000 tokens is the first total >= 3500
    assert result["tokens_used"] == 4_000


def test_hard_limit_stops_the_loop_even_if_graceful_rules_are_off():
    # Both graceful limits are effectively disabled: only LangGraph's limit is left.
    model = forever_model()
    limits = Limits(max_steps=10**9, max_tokens=10**9)
    with pytest.raises(GraphRecursionError):
        run(model, limits, {"recursion_limit": 20})
    assert model.calls <= 20
