"""Tools: strict inputs, clear errors, idempotent writes, every call logged (Tasks T3.5).

Tools are called through the real agent graph, driven by the scripted fake model,
so these tests cover the schema, the error text and the call log together.
"""

import hashlib
import json

import pytest
from langchain.messages import HumanMessage

from agent.graph import build_graph, run_config
from agent.stop import Limits
from agent.tools import make_tools
from eval.fake_model import FakeModel
from sandbox.seed import seed

FIX = {"date_format": "%Y-%m-%d"}  # the repair for the bad_date_format fault


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "work"
    seed("bad_date_format", "load_orders", folder)
    return folder


def call_tools(work, *calls):
    """Run the given (tool, args) calls in order; return the text of each result."""
    model = FakeModel(script=[[call] for call in calls])
    limits = Limits(max_steps=len(calls) + 1)
    graph = build_graph(model, make_tools(work), limits, log_path=work / "tool_calls.jsonl")
    result = graph.invoke({"messages": [HumanMessage("go")]}, run_config(limits))
    return [m.content for m in result["messages"] if m.type == "tool"]


def files_state(work) -> dict:
    return {
        path.relative_to(work).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(work.rglob("*"))
        if path.is_file() and path.name != "tool_calls.jsonl"
    }


# ---- the normal repair path -------------------------------------------------

def test_full_repair_with_the_tools(work):
    failed, log, check, update, rerun, after = call_tools(
        work,
        ("list_failed_runs", {}),
        ("get_run_logs", {"run_id": "run_0004"}),
        ("validate_config", {"job_id": "load_orders", "changes": FIX}),
        ("update_job_config", {"job_id": "load_orders", "changes": FIX}),
        ("rerun_job", {"job_id": "load_orders"}),
        ("list_failed_runs", {}),
    )
    assert json.loads(failed)[0]["run_id"] == "run_0004"
    assert "ERROR E_DATE_FORMAT" in log
    assert json.loads(check) == {"valid": True, "rows_that_would_load": 200}
    assert json.loads(update)["changed"] == {"date_format": {"old": "%Y/%m/%d", "new": "%Y-%m-%d"}}
    assert json.loads(rerun)["status"] == "success"
    assert after.startswith("No job is currently failing")  # the "empty result" case


def test_validate_config_reports_a_bad_fix_and_changes_nothing(work):
    before = files_state(work)
    [answer] = call_tools(work, ("validate_config", {"job_id": "load_orders", "changes": {"date_format": "%d/%m/%Y"}}))
    assert json.loads(answer)["valid"] is False
    assert "E_DATE_FORMAT" in answer
    assert files_state(work) == before


# ---- strict inputs and clear errors -----------------------------------------

BAD_CALLS = [
    ("get_run_logs", {"run_id": "../../secret"}, "E_BAD_ARGUMENTS"),
    ("get_run_logs", {"run_id": "run_0004", "tail_lines": 5000}, "E_BAD_ARGUMENTS"),
    ("get_run_logs", {"run_id": "run_0099"}, "E_NOT_FOUND"),
    ("get_job_config", {"job_id": "no_such_job"}, "E_NOT_FOUND"),
    ("get_job_config", {}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {}}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {"owner": "me"}}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {"batch_size": 50000}}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {"source_path": "../x.csv"}}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {"columns": ["a; DROP TABLE runs"]}}, "E_BAD_ARGUMENTS"),
    ("update_job_config", {"job_id": "load_orders", "changes": {"target_table": "prod_users"}}, "E_NOT_ALLOWED"),
    ("rerun_job", {"job_id": "load_orders", "times": 100}, "E_BAD_ARGUMENTS"),
    ("delete_job", {"job_id": "load_orders"}, "not a valid tool"),
]


@pytest.mark.parametrize("tool_name, args, expected", BAD_CALLS)
def test_bad_calls_get_a_clear_error_and_change_nothing(work, tool_name, args, expected):
    before = files_state(work)
    [answer] = call_tools(work, (tool_name, args))
    assert expected in answer
    assert "Traceback" not in answer
    assert files_state(work) == before


def test_missing_table_key_can_be_added_but_not_changed_afterwards(tmp_path):
    work = tmp_path / "work"
    seed("missing_key", "load_orders", work)
    add = ("update_job_config", {"job_id": "load_orders", "changes": {"target_table": "orders"}})
    change = ("update_job_config", {"job_id": "load_orders", "changes": {"target_table": "other"}})
    first, second = call_tools(work, add, change)
    assert json.loads(first)["status"] == "updated"
    assert "E_NOT_ALLOWED" in second


# ---- idempotent writes ------------------------------------------------------

def test_update_twice_changes_the_config_once(work):
    update = ("update_job_config", {"job_id": "load_orders", "changes": FIX})
    first, = call_tools(work, update)
    after_first = files_state(work)
    second, = call_tools(work, update)
    assert json.loads(first)["status"] == "updated"
    assert json.loads(second)["status"] == "no_change"
    assert files_state(work) == after_first  # no second write, no second backup
    assert len(list((work / "backups").iterdir())) == 1


def test_rerun_twice_starts_one_run(work):
    update = ("update_job_config", {"job_id": "load_orders", "changes": FIX})
    rerun = ("rerun_job", {"job_id": "load_orders"})
    _, first, second, history = call_tools(work, update, rerun, rerun, ("list_job_runs", {"job_id": "load_orders"}))
    assert json.loads(first)["already_ran"] is False
    assert json.loads(second)["already_ran"] is True
    assert json.loads(second)["run_id"] == json.loads(first)["run_id"]
    assert [run["run_id"] for run in json.loads(history)] == ["run_0005", "run_0004", "run_0003"]


def test_rerun_without_a_config_change_starts_no_run(work):
    [answer] = call_tools(work, ("rerun_job", {"job_id": "load_orders"}))
    assert json.loads(answer)["already_ran"] is True
    assert json.loads(answer)["run_id"] == "run_0004"  # still the failed run


# ---- the call log -----------------------------------------------------------

def test_every_call_is_logged_with_input_output_and_time(work):
    call_tools(
        work,
        ("list_failed_runs", {}),
        ("get_run_logs", {"run_id": "run_0099"}),
        ("update_job_config", {"job_id": "load_orders", "changes": FIX}),
    )
    lines = (work / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    assert [entry["tool"] for entry in entries] == ["list_failed_runs", "get_run_logs", "update_job_config"]
    assert [entry["status"] for entry in entries] == ["success", "error", "success"]
    assert entries[2]["input"] == {"job_id": "load_orders", "changes": FIX}
    for entry in entries:
        assert entry["time"] and entry["output"] and entry["duration_ms"] >= 0
