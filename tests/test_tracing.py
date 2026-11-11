"""LangSmith tracing is on only when it is switched on AND a key is present."""

import pytest

from agent.tracing import configure_tracing, log_scores, traced_run


@pytest.mark.parametrize("switch, key, expected", [
    ("true", "a-key", True),
    ("true", "", False),    # the placeholder line was left empty
    ("false", "a-key", False),
    ("", "a-key", False),
])
def test_tracing_needs_the_switch_and_a_key(monkeypatch, switch, key, expected):
    monkeypatch.setenv("LANGSMITH_TRACING", switch)
    monkeypatch.setenv("LANGSMITH_API_KEY", key)
    assert configure_tracing() is expected


def test_with_tracing_off_nothing_is_traced_and_nothing_breaks(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    with traced_run("a-run", ["eval"], {"scenario": "x"}) as root:
        assert root is None
        log_scores(root, {"stop_reason": "done"}, {"success": 1.0})  # must be a no-op
