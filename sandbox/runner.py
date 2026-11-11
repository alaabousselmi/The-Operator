"""The mini data pipeline: a job reads a CSV file and loads it into a SQLite table.

A job is described by sandbox/.work/jobs/<job_id>.json. Every run adds a row to the
`runs` table and writes a log file to logs/<run_id>.log. Failures are real: the
runner fails because the config or the data is actually wrong.

Two resources are simulated so that runs stay instant and repeatable:
- time:   a job "takes" SECONDS_PER_ROW per row; over `timeout_seconds` it fails.
- memory: a batch larger than MAX_BATCH_ROWS "does not fit" in the worker.
"""

import csv
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sandbox.paths import WORK, resolve_inside

REQUIRED_KEYS = [
    "source_path", "delimiter", "columns", "date_column",
    "date_format", "batch_size", "timeout_seconds", "target_table",
]
SECONDS_PER_ROW = 0.05
MAX_BATCH_ROWS = 1000
NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # safe job, table and column names


class JobError(Exception):
    """A job failure with a short code and a message a person (or a model) can act on."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def connect(work: Path) -> sqlite3.Connection:
    return sqlite3.connect(work / "pipeline.db")


def init_db(work: Path) -> None:
    with closing(connect(work)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, job_id TEXT, "
            "status TEXT, error_code TEXT, rows_loaded INTEGER, config_hash TEXT, "
            "started_at TEXT, ended_at TEXT, config TEXT)"
        )


def load_config(work: Path, job_id: str) -> dict:
    if not NAME.match(job_id):
        raise ValueError(f"invalid job id '{job_id}'")
    path = work / "jobs" / f"{job_id}.json"
    if not path.exists():
        known = sorted(p.stem for p in (work / "jobs").glob("*.json"))
        raise ValueError(f"unknown job '{job_id}'. Known jobs: {known}")
    return json.loads(path.read_text(encoding="utf-8"))


def config_hash(config: dict) -> str:
    """Short fingerprint of a config. Same config, same hash."""
    text = json.dumps(config, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def check_config(config: dict) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise JobError("E_CONFIG_KEY_MISSING", f"config has no key(s) {missing}")
    names = [config["target_table"], *config["columns"]]
    bad = [n for n in names if not isinstance(n, str) or not NAME.match(n)]
    if bad or config["target_table"] == "runs":
        raise JobError("E_CONFIG_INVALID", f"invalid table or column name(s): {bad or ['runs']}")
    if config["batch_size"] > MAX_BATCH_ROWS:
        raise JobError(
            "E_OUT_OF_MEMORY",
            f"batch_size {config['batch_size']} does not fit in worker memory "
            f"(max {MAX_BATCH_ROWS} rows per batch)",
        )


def read_rows(work: Path, config: dict) -> list[dict]:
    """Read and validate the source file. Raise JobError on the first problem."""
    try:
        source = resolve_inside(work, config["source_path"])
    except ValueError as error:
        raise JobError("E_PATH_OUTSIDE_SANDBOX", str(error))
    if not source.is_file():
        available = sorted(p.name for p in (work / "data").glob("*.csv"))
        raise JobError(
            "E_SOURCE_NOT_FOUND",
            f"source file '{config['source_path']}' not found. Files in data/: {available}",
        )
    with source.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file, delimiter=config["delimiter"])
        header = next(reader, [])
        missing = [column for column in config["columns"] if column not in header]
        if missing:
            raise JobError(
                "E_COLUMN_MISSING",
                f"column(s) {missing} not in source. Header read with delimiter "
                f"'{config['delimiter']}' is {header}",
            )
        rows = []
        for number, values in enumerate(reader, start=2):  # line 1 is the header
            if len(values) != len(header):
                raise JobError(
                    "E_BAD_ROW",
                    f"line {number} of the source has {len(values)} fields, expected "
                    f"{len(header)}. The source data is damaged",
                )
            row = dict(zip(header, values))
            try:
                datetime.strptime(row[config["date_column"]], config["date_format"])
            except (ValueError, KeyError):
                raise JobError(
                    "E_DATE_FORMAT",
                    f"line {number}: value '{row.get(config['date_column'])}' in column "
                    f"'{config['date_column']}' does not match date_format "
                    f"'{config['date_format']}'",
                )
            rows.append(row)
    needed = len(rows) * SECONDS_PER_ROW
    if needed > config["timeout_seconds"]:
        raise JobError(
            "E_TIMEOUT",
            f"job needs about {needed:.0f}s for {len(rows)} rows but timeout_seconds "
            f"is {config['timeout_seconds']}",
        )
    return rows


def write_rows(db: sqlite3.Connection, config: dict, rows: list[dict]) -> None:
    """Replace the target table with the rows. Re-running loads the same data once."""
    table, columns = config["target_table"], config["columns"]
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in columns)})")
    insert = f"INSERT INTO {table} VALUES ({', '.join('?' for _ in columns)})"
    size = config["batch_size"]
    for start in range(0, len(rows), size):
        batch = rows[start:start + size]
        db.executemany(insert, [[row[c] for c in columns] for row in batch])


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_job(job_id: str, work: Path = WORK) -> dict:
    """Run one job. Always records the run and its log, whether it succeeds or fails."""
    config = load_config(work, job_id)
    started = now()
    with closing(connect(work)) as db:
        count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        run_id = f"run_{count + 1:04d}"
        log = [f"INFO job={job_id} run={run_id} started", f"INFO config {json.dumps(config)}"]
        status, error_code, loaded = "success", None, 0
        try:
            check_config(config)
            log.append(f"INFO reading {config['source_path']}")
            rows = read_rows(work, config)
            with db:
                write_rows(db, config, rows)
            loaded = len(rows)
            log.append(f"INFO loaded {loaded} rows into table '{config['target_table']}'")
        except JobError as error:
            status, error_code = "failed", error.code
            log.append(f"ERROR {error}")
        log.append(f"INFO run finished status={status}")
        with db:
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, job_id, status, error_code, loaded, config_hash(config), started, now(),
                 json.dumps(config)),
            )
    (work / "logs" / f"{run_id}.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return {"run_id": run_id, "job_id": job_id, "status": status,
            "error_code": error_code, "rows_loaded": loaded}
