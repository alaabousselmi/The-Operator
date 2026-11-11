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

NO_LIMIT = 10**9
tool_runs = []


@tool
def ping(n: int = 0) -> str:
    """Do nothing and return ok."""
    tool_runs.append(n)
    return "ok"


def run(work, model, limits, config=None):
    tool_runs.clear()
    graph = build_graph(model, work, limits, tools=[ping])
    start = {"messages": [HumanMessage("repair the job")]}
    return graph.invoke(start, config or run_config(limits))


def forever_model(**kwargs):
    """Asks for the same tool call on every turn, forever."""
    return FakeModel(script=[[("ping", {})]], loop_forever=True, **kwargs)


def test_normal_run_stops_when_model_is_done(tmp_path):
    model = FakeModel(script=[[("ping", {"n": 1})], [("ping", {"n": 2})]])
    result = run(tmp_path, model, Limits(max_steps=10))
    assert result["stop_reason"] == "done"
    assert result["steps"] == 3  # two tool turns + one final answer
    assert tool_runs == [1, 2]


@pytest.mark.parametrize("max_steps", [1, 2, 5, 12, 30])
def test_looping_model_is_stopped_by_max_steps(tmp_path, max_steps):
    model = forever_model()
    result = run(tmp_path, model, Limits(max_steps=max_steps, max_tokens=NO_LIMIT, max_repeats=NO_LIMIT))
    assert result["stop_reason"] == "max_steps"
    assert model.calls == max_steps  # never one call more than allowed
    assert result["steps"] == max_steps
    assert len(tool_runs) == max_steps - 1  # the last tool request is not executed
    assert "max_steps" in result["messages"][-1].content


def test_looping_model_is_stopped_by_token_budget(tmp_path):
    model = forever_model(tokens_per_call=1_000)
    limits = Limits(max_steps=NO_LIMIT, max_tokens=3_500, max_repeats=NO_LIMIT)
    result = run(tmp_path, model, limits, {"recursion_limit": 100, "configurable": {"thread_id": "t"}})
    assert result["stop_reason"] == "budget"
    assert model.calls == 4  # 4 x 1000 tokens is the first total >= 3500
    assert result["tokens_used"] == 4_000


def test_repeating_the_same_call_is_stopped_as_a_loop(tmp_path):
    model = forever_model()
    result = run(tmp_path, model, Limits(max_steps=50, max_repeats=3))
    assert result["stop_reason"] == "loop"
    assert len(tool_runs) == 3  # the identical call ran 3 times; the 4th request was refused
    assert model.calls == 4


def test_hard_limit_stops_the_loop_even_if_graceful_rules_are_off(tmp_path):
    # All graceful limits are effectively disabled: only LangGraph's limit is left.
    model = forever_model()
    limits = Limits(max_steps=NO_LIMIT, max_tokens=NO_LIMIT, max_repeats=NO_LIMIT)
    with pytest.raises(GraphRecursionError):
        run(tmp_path, model, limits, {"recursion_limit": 20, "configurable": {"thread_id": "t"}})
    assert model.calls <= 20
