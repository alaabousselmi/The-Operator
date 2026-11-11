"""One test per error class of errors.md (Tasks T6.2).

The scripted model decides what the "agent" asks for; each test shows what the
system does about it: the text the model gets back, what changes in the sandbox,
and how the run ends. How often the real model recovers is measured by the eval.
"""

import json
import sqlite3
from contextlib import closing

import pytest

from agent.run import run_agent
from agent.stop import Limits
from eval.fake_model import FakeModel
from sandbox.seed import seed

JOB = "load_orders"
FIX = {"date_format": "%Y-%m-%d"}
LIST = ("list_failed_runs", {})
LOGS = ("get_run_logs", {"run_id": "run_0004"})
UPDATE = ("update_job_config", {"job_id": JOB, "changes": FIX})
RERUN = ("rerun_job", {"job_id": JOB})
YES = lambda request: {"approved": True}  # noqa: E731


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "work"
    seed("bad_date_format", JOB, folder)
    return folder


def run(work, calls, approve=YES, failures=None, loop_forever=False, limits=Limits()):
    model = FakeModel(script=[[call] for call in calls], loop_forever=loop_forever)
    state = run_agent(model, approve, work, limits, tool_failures=failures)
    return state, [m.content for m in state["messages"] if m.type == "tool"]


def config(work, job=JOB) -> dict:
    return json.loads((work / "jobs" / f"{job}.json").read_text(encoding="utf-8"))


def runs(work) -> list:
    with closing(sqlite3.connect(work / "pipeline.db")) as db:
        return db.execute("SELECT run_id, job_id, status FROM runs ORDER BY run_id").fetchall()


def test_tool_down_once_the_retry_succeeds(work):
    state, (first, second) = run(work, [LOGS, LOGS], failures={"get_run_logs": ["unavailable"]})
    assert first.startswith("ERROR E_TOOL_UNAVAILABLE") and "Retry" in first
    assert "ERROR E_DATE_FORMAT" in second  # the retry returned the real log
    assert state["stop_reason"] == "done"


def test_tool_down_for_good_the_run_stops_without_writing(work):
    before = config(work)
    state, answers = run(work, [UPDATE], failures={"update_job_config": ["unavailable"] * 9}, loop_forever=True)
    assert state["stop_reason"] == "loop"
    assert len(answers) == 3  # one try + two retries, then the loop rule ends the run
    assert config(work) == before


def test_bad_arguments_are_refused_with_a_message_the_model_can_fix(work):
    bad = ("update_job_config", {"job_id": JOB, "changes": {"date_format": "%Y-%m-%d", "batch_size": 50000}})
    state, (first, second) = run(work, [bad, UPDATE])
    assert first.startswith("ERROR E_BAD_ARGUMENTS: changes.batch_size")
    assert json.loads(second)["status"] == "updated"  # the corrected call works


def test_empty_result_is_stated_in_words(tmp_path):
    work = tmp_path / "work"
    seed(None, JOB, work)  # a healthy sandbox
    state, (answer,) = run(work, [LIST])
    assert answer == "No job is currently failing. Nothing to repair."


def test_empty_result_from_a_failing_tool_can_be_retried(work):
    state, (first, second) = run(work, [LOGS, LOGS], failures={"get_run_logs": ["empty"]})
    assert first == "" and "ERROR E_DATE_FORMAT" in second


def test_wrong_tool_a_tool_that_does_not_exist(work):
    before = config(work)
    state, (answer,) = run(work, [("delete_job", {"job_id": JOB})])
    assert "delete_job is not a valid tool" in answer and "list_failed_runs" in answer
    assert config(work) == before


def test_wrong_tool_a_write_on_a_healthy_job_is_refused(work):
    before = config(work, "load_customers")
    state, (answer,) = run(work, [("update_job_config", {"job_id": "load_customers", "changes": {"batch_size": 10}})])
    assert answer.startswith("ERROR E_NOT_ALLOWED: Job load_customers already passes")
    assert config(work, "load_customers") == before


def test_loop_the_same_call_again_and_again_is_stopped(work):
    state, answers = run(work, [LOGS], loop_forever=True)
    assert state["stop_reason"] == "loop"
    assert state["steps"] == 4 and len(answers) == 3


def test_tool_timeout_once_the_retry_succeeds(work):
    state, (first, second) = run(work, [RERUN, RERUN], failures={"rerun_job": ["timeout"]})
    assert first.startswith("ERROR E_TOOL_TIMEOUT")
    assert json.loads(second)["run_id"] == "run_0004"  # the tool answered on the retry


def test_job_timeout_is_a_fault_the_agent_can_repair(tmp_path):
    work = tmp_path / "work"
    seed("timeout_too_low", JOB, work)
    change = {"job_id": JOB, "changes": {"timeout_seconds": 30}}
    state, answers = run(work, [("validate_config", change), ("update_job_config", change), RERUN])
    assert json.loads(answers[-1])["status"] == "success"


def test_user_changes_mind_the_rejection_reaches_the_model_and_nothing_is_written(work):
    before = config(work)
    no = lambda request: {"approved": False, "reason": "wait for the data team"}  # noqa: E731
    state, (answer,) = run(work, [UPDATE], approve=no)
    assert answer.startswith("REJECTED by the human reviewer. Reason: wait for the data team")
    assert config(work) == before and state["stop_reason"] == "done"


def test_partial_failure_step_3_of_5_fails_and_a_second_run_finishes_the_job(work):
    """update succeeds, rerun is down: the run ends cleanly; running the agent again completes it."""
    state, answers = run(work, [UPDATE, RERUN], failures={"rerun_job": ["unavailable"] * 9}, loop_forever=False)
    assert config(work)["date_format"] == "%Y-%m-%d"  # step done
    assert runs(work)[-1] == ("run_0004", JOB, "failed")  # step not done: still failing
    assert len(list((work / "backups").iterdir())) == 1  # the old config can be restored
    # Second run: the config is already right, so only the re-run is left.
    state, answers = run(work, [LIST, UPDATE, RERUN])
    assert json.loads(answers[1])["status"] == "no_change"  # idempotent: not written twice
    assert json.loads(answers[2])["status"] == "success"
    assert runs(work)[-1] == ("run_0005", JOB, "success")


def test_stopped_by_a_limit_mid_repair_reports_the_writes_done(work):
    state, answers = run(work, [UPDATE, LIST, LIST], limits=Limits(max_steps=2))
    assert state["stop_reason"] == "max_steps"
    assert "Writes executed so far: ['update_job_config']" in state["messages"][-1].content


def test_unfixable_fault_no_config_write_is_accepted(tmp_path):
    work = tmp_path / "work"
    seed("corrupt_source", JOB, work)
    before, runs_before = config(work), runs(work)
    guess = ("update_job_config", {"job_id": JOB, "changes": {"delimiter": ";"}})
    state, (update, rerun) = run(work, [guess, RERUN])
    assert update.startswith("ERROR E_NOT_ALLOWED: The job would still fail")
    assert json.loads(rerun)["already_ran"] is True  # no pointless new run either
    assert config(work) == before and runs(work) == runs_before


def test_over_fixing_extra_keys_are_refused(work):
    """The repair plus an unneeded change (what an injected 'operator note' asks for)."""
    before = config(work)
    extra = ("update_job_config", {"job_id": JOB, "changes": {**FIX, "batch_size": 1, "timeout_seconds": 300}})
    state, (answer,) = run(work, [extra])
    assert answer.startswith("ERROR E_NOT_ALLOWED: Key(s) ['batch_size', 'timeout_seconds'] do not need to change")
    assert config(work) == before
