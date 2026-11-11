"""Reset the sandbox to a clean state:  python -m sandbox.reset

Deletes the live sandbox and rebuilds it from sandbox/templates, then runs every job
once so each job has a successful run in its history.
"""

import shutil
from pathlib import Path

from sandbox.paths import MARKER, TEMPLATES, WORK
from sandbox.runner import init_db, run_job


def reset(work: Path = WORK) -> None:
    if work.exists():
        # Safety: only ever delete a folder that we created ourselves.
        if any(work.iterdir()) and not (work / MARKER).exists():
            raise RuntimeError(f"refusing to delete {work}: it is not a sandbox")
        shutil.rmtree(work)
    shutil.copytree(TEMPLATES, work)
    (work / MARKER).write_text("created by sandbox.reset\n", encoding="utf-8")
    (work / "logs").mkdir()
    init_db(work)
    for job_file in sorted((work / "jobs").glob("*.json")):
        run_job(job_file.stem, work)


if __name__ == "__main__":
    reset()
    print(f"sandbox reset: {WORK}")
