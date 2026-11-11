"""The sandbox works, really fails, and can always be reset (Tasks T2.4)."""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from sandbox.faults import FAULTS
from sandbox.paths import resolve_inside
from sandbox.reset import reset
from sandbox.runner import run_job
from sandbox.seed import seed

JOBS = ["load_customers", "load_events", "load_orders"]


def snapshot(work) -> dict:
    """Everything that defines the sandbox state, except run timestamps."""
    state = {}
    for path in sorted(work.rglob("*")):
        if path.is_file() and path.suffix != ".db":
            state[path.relative_to(work).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(work / "pipeline.db")) as db:
        state["runs"] = db.execute(
            "SELECT run_id, job_id, status, error_code, rows_loaded, config_hash FROM runs"
        ).fetchall()
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        for table in tables:
            state[f"table:{table}"] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return state


def test_clean_sandbox_has_one_successful_run_per_job(tmp_path):
    work = tmp_path / "work"
    reset(work)
    runs = snapshot(work)["runs"]
    assert [(job, status, rows) for _, job, status, _, rows, _ in runs] == [
        (job, "success", 200) for job in JOBS
    ]


@pytest.mark.parametrize("job_id", JOBS)
@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_every_fault_really_fails_every_job(tmp_path, fault, job_id):
    work = tmp_path / "work"
    result = seed(fault, job_id, work)
    assert result["status"] == "failed"
    assert result["error_code"] == FAULTS[fault][1]
    log = (work / "logs" / f"{result['run_id']}.log").read_text(encoding="utf-8")
    assert f"ERROR {result['error_code']}" in log
    assert "Traceback" not in log


def test_reset_restores_the_same_state_after_damage(tmp_path):
    work = tmp_path / "work"
    reset(work)
    clean = snapshot(work)
    seed("corrupt_source", "load_orders", work)
    seed("missing_key", "load_events", work)
    (work / "jobs" / "load_customers.json").unlink()
    assert snapshot(work) != clean
    reset(work)
    assert snapshot(work) == clean


def test_rerun_does_not_duplicate_rows(tmp_path):
    work = tmp_path / "work"
    reset(work)
    run_job("load_orders", work)
    run_job("load_orders", work)
    assert snapshot(work)["table:orders"] == 200


def test_reset_refuses_to_delete_a_folder_that_is_not_a_sandbox(tmp_path):
    (tmp_path / "important.txt").write_text("keep me")
    with pytest.raises(RuntimeError):
        reset(tmp_path)
    assert (tmp_path / "important.txt").exists()


def test_paths_cannot_leave_the_sandbox(tmp_path):
    work = tmp_path / "work"
    reset(work)
    with pytest.raises(ValueError):
        resolve_inside(work, "../outside.csv")
    # A job config pointing outside the sandbox fails cleanly instead of reading the file.
    (tmp_path / "secret.csv").write_text("order_id,customer_id,amount,order_date\n")
    config_path = work / "jobs" / "load_orders.json"
    config_path.write_text(config_path.read_text().replace("data/orders.csv", "../secret.csv"))
    assert run_job("load_orders", work)["error_code"] == "E_PATH_OUTSIDE_SANDBOX"
