"""The agent's tools: five that read, two that write.

Read : list_failed_runs, list_job_runs, get_run_logs, get_job_config, validate_config
Write: update_job_config, rerun_job

Every tool has a strict pydantic schema: unknown fields, bad ids and out-of-range
values are rejected before the tool body runs. Tools signal expected problems by
raising ToolError; agent/calls.py turns every error into one clear line for the model.
There is deliberately no delete tool, no shell tool and no free file-path tool.
"""

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sandbox.paths import WORK
from sandbox.runner import (
    MAX_BATCH_ROWS, JobError, check_config, config_hash, connect, load_config,
    read_rows, run_job,
)

WRITE_TOOLS = {"update_job_config", "rerun_job"}  # these need human approval

NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
JobId = Annotated[str, Field(pattern=NAME_PATTERN, max_length=40, description="Job id, e.g. load_orders")]
RunId = Annotated[str, Field(pattern=r"^run_\d{4}$", description="Run id, e.g. run_0004")]
Name = Annotated[str, Field(pattern=NAME_PATTERN, max_length=40)]


class ToolError(Exception):
    """An expected tool failure: a short code, what happened, and what to try next."""

    def __init__(self, code: str, message: str, hint: str):
        super().__init__(f"ERROR {code}: {message} {hint}")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are an error


class NoArgs(Strict):
    pass


class JobArgs(Strict):
    job_id: JobId


class RunLogArgs(Strict):
    run_id: RunId
    tail_lines: int = Field(default=50, ge=1, le=200, description="How many last lines to return")


class ConfigChanges(Strict):
    """The only config keys that can be changed, each with its allowed values."""

    source_path: str | None = Field(default=None, pattern=r"^data/[A-Za-z0-9_.-]+\.csv$")
    delimiter: Literal[",", ";", "|", "\t"] | None = None
    columns: list[Name] | None = Field(default=None, min_length=1, max_length=20)
    date_column: Name | None = None
    date_format: str | None = Field(default=None, pattern=r"^[%A-Za-z/.: -]{2,20}$")
    batch_size: int | None = Field(default=None, ge=1, le=MAX_BATCH_ROWS)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    target_table: Name | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("changes is empty: give at least one key to change")
        return self


class ChangeArgs(Strict):
    job_id: JobId
    changes: ConfigChanges


def to_text(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def make_tools(work: Path = WORK) -> list:
    """Create the tools, bound to one sandbox folder."""

    def get_config(job_id: str) -> dict:
        try:
            return load_config(work, job_id)
        except ValueError as error:  # unknown job: the message lists the known jobs
            raise ToolError("E_NOT_FOUND", f"{error}.", "Use a job id from list_failed_runs.")

    def query(sql: str, *params) -> list[dict]:
        with closing(connect(work)) as db:
            cursor = db.execute(sql, params)
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def new_config(job_id: str, changes: ConfigChanges) -> tuple[dict, dict]:
        """Return (current config, config after the changes)."""
        old = get_config(job_id)
        wanted = changes.model_dump(exclude_unset=True)
        if "target_table" in old and wanted.get("target_table", old["target_table"]) != old["target_table"]:
            raise ToolError(
                "E_NOT_ALLOWED", "target_table is already set and cannot be changed.",
                "Leave target_table out of changes.",
            )
        return old, {**old, **wanted}

    def passes(config: dict) -> bool:
        """Dry run: would the job succeed with this config?"""
        try:
            check_config(config)
            read_rows(work, config)
            return True
        except JobError:
            return False

    def without_change(old: dict, new: dict, key: str) -> dict:
        """The new config, but with one key put back to its old value (or removed)."""
        config = dict(new)
        if key in old:
            config[key] = old[key]
        else:
            del config[key]
        return config

    @tool(args_schema=NoArgs)
    def list_failed_runs() -> str:
        """List the jobs whose most recent run failed. Start here to find what to repair."""
        rows = query(
            "SELECT job_id, run_id, error_code, ended_at FROM runs WHERE status = 'failed' "
            "AND run_id IN (SELECT MAX(run_id) FROM runs GROUP BY job_id) ORDER BY run_id"
        )
        return to_text(rows) if rows else "No job is currently failing. Nothing to repair."

    @tool(args_schema=JobArgs)
    def list_job_runs(job_id: str) -> str:
        """List the last 10 runs of one job, newest first, with status and error code."""
        get_config(job_id)  # raises a clear error if the job does not exist
        rows = query(
            "SELECT run_id, status, error_code, rows_loaded, config_hash, ended_at "
            "FROM runs WHERE job_id = ? ORDER BY run_id DESC LIMIT 10", job_id,
        )
        return to_text(rows) if rows else f"Job {job_id} has never run."

    @tool(args_schema=RunLogArgs)
    def get_run_logs(run_id: str, tail_lines: int = 50) -> str:
        """Read the last lines of the log of one run. The log shows the config used and the error."""
        path = work / "logs" / f"{run_id}.log"
        if not path.is_file():
            raise ToolError("E_NOT_FOUND", f"No log for run '{run_id}'.", "Get run ids from list_failed_runs or list_job_runs.")
        lines = path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-tail_lines:])

    @tool(args_schema=JobArgs)
    def get_job_config(job_id: str) -> str:
        """Read the current config of one job."""
        return to_text(get_config(job_id))

    @tool(args_schema=ChangeArgs)
    def validate_config(job_id: str, changes: ConfigChanges) -> str:
        """Dry run: check whether a job would succeed with these config changes. Changes nothing. Use it before update_job_config."""
        _, config = new_config(job_id, changes)
        try:
            check_config(config)
            rows = read_rows(work, config)
        except JobError as error:
            return to_text({"valid": False, "error": str(error)})
        return to_text({"valid": True, "rows_that_would_load": len(rows)})

    @tool(args_schema=ChangeArgs)
    def update_job_config(job_id: str, changes: ConfigChanges) -> str:
        """WRITE. Change keys in a failing job's config (the old config is backed up). Needs human approval. Accepted only if the job fails now, passes with the changes, and every changed key is needed for that. Calling it again with the same changes does nothing."""
        old, new = new_config(job_id, changes)
        if new == old:
            return to_text({"status": "no_change", "detail": "config already has these values"})
        # A write is only accepted if it is a minimal repair. These three checks are the
        # code-level limit on what any instruction, real or injected, can make the agent write.
        if passes(old):
            raise ToolError("E_NOT_ALLOWED", f"Job {job_id} already passes with its current config, so nothing needs to change.", "Do not change a job that is not broken.")
        if not passes(new):
            raise ToolError("E_NOT_ALLOWED", "The job would still fail with these changes.", "Use validate_config to find a change that works.")
        changed_keys = [key for key in new if old.get(key) != new[key]]
        not_needed = [key for key in changed_keys if passes(without_change(old, new, key))]
        if not_needed:
            raise ToolError("E_NOT_ALLOWED", f"Key(s) {not_needed} do not need to change: the job passes without changing them.", "Send only the keys that fix the error.")
        backups = work / "backups"
        backups.mkdir(exist_ok=True)
        # The backup is named after the old config's hash, so a repeat cannot pile up copies.
        (backups / f"{job_id}.{config_hash(old)}.json").write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
        path = work / "jobs" / f"{job_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)  # swap in one step: the config is never half-written
        changed = {key: {"old": old.get(key), "new": new[key]} for key in new if old.get(key) != new[key]}
        return to_text({"status": "updated", "changed": changed, "config_hash": config_hash(new)})

    @tool(args_schema=JobArgs)
    def rerun_job(job_id: str) -> str:
        """WRITE. Run a job again with its current config and return the result. Needs human approval. If the config has not changed since the job's last run, no new run is started."""
        config = get_config(job_id)
        last = query(
            "SELECT run_id, status, error_code, rows_loaded, config_hash FROM runs "
            "WHERE job_id = ? ORDER BY run_id DESC LIMIT 1", job_id,
        )
        if last and last[0]["config_hash"] == config_hash(config):
            del last[0]["config_hash"]
            return to_text({"already_ran": True, **last[0], "detail": "config unchanged since this run; no new run started"})
        result = run_job(job_id, work)
        return to_text({"already_ran": False, **result})

    return [list_failed_runs, list_job_runs, get_run_logs, get_job_config,
            validate_config, update_job_config, rerun_job]
