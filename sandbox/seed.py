"""Put the sandbox in a broken state:  python -m sandbox.seed <fault> [job_id]

Resets the sandbox, applies one fault from the catalogue to one job, and runs that
job so it fails. This is the starting point of every scenario.
"""

import sys
from pathlib import Path

from sandbox.faults import FAULTS
from sandbox.paths import WORK
from sandbox.reset import reset
from sandbox.runner import run_job


def seed(fault: str, job_id: str = "load_orders", work: Path = WORK) -> dict:
    if fault not in FAULTS:
        raise ValueError(f"unknown fault '{fault}'. Known faults: {sorted(FAULTS)}")
    reset(work)
    apply_fault = FAULTS[fault][0]
    apply_fault(work, job_id)
    return run_job(job_id, work)  # the failed run the agent will have to repair


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"usage: python -m sandbox.seed <fault> [job_id]\nfaults: {sorted(FAULTS)}")
    print(seed(*sys.argv[1:3]))
