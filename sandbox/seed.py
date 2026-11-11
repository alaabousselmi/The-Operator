"""Put the sandbox in a broken state:  python -m sandbox.seed <fault> [job_id]

Resets the sandbox, applies one fault from the catalogue to one job, and runs that
job so it fails. This is the starting point of every scenario.

For the injection tests, `inject` plants attacker text where the agent will read it:
    {"where": "log",    "text": ...}  extra lines in the failed run's log
    {"where": "config", "text": ...}  a "note" key in the job config
    {"where": "data",   "text": ...}  a cell of the source file (echoed by the error)
"""

import csv
import sys
from pathlib import Path

from sandbox.faults import FAULTS, edit_config
from sandbox.paths import WORK
from sandbox.reset import reset
from sandbox.runner import load_config, run_job


def poison_data(work: Path, job_id: str, text: str) -> None:
    """Replace the date cell of the first data row with the attacker's text."""
    config = load_config(work, job_id)
    path = work / config["source_path"]
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file, delimiter=config["delimiter"]))
    rows[1][rows[0].index(config["date_column"])] = text
    with path.open("w", newline="", encoding="utf-8") as file:
        csv.writer(file, delimiter=config["delimiter"], lineterminator="\n").writerows(rows)


def poison_log(work: Path, run_id: str, text: str) -> None:
    """Insert the attacker's text in a run log, just before its last line."""
    path = work / "logs" / f"{run_id}.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1:-1] = text.splitlines()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed(fault: str | None, job_id: str = "load_orders", work: Path = WORK, inject: dict | None = None) -> dict | None:
    """Reset, break one job and run it. Return the failed run (None if nothing was run).

    fault=None leaves the job healthy unless `inject` damages its data.
    """
    if fault is not None and fault not in FAULTS:
        raise ValueError(f"unknown fault '{fault}'. Known faults: {sorted(FAULTS)}")
    reset(work)
    if fault is not None:
        FAULTS[fault][0](work, job_id)
    where = (inject or {}).get("where")
    if where == "config":
        edit_config(work, job_id, note=inject["text"])
    if where == "data":
        poison_data(work, job_id, inject["text"])
    if fault is None and where is None:
        return None  # a clean sandbox: nothing is failing
    failed = run_job(job_id, work)  # the failed run the agent will have to repair
    if where == "log":
        poison_log(work, failed["run_id"], inject["text"])
    return failed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"usage: python -m sandbox.seed <fault> [job_id]\nfaults: {sorted(FAULTS)}")
    print(seed(*sys.argv[1:3]))
