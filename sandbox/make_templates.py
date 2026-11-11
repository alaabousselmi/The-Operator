"""Generate the clean template jobs and data:  python -m sandbox.make_templates

Run once; the output in sandbox/templates is committed. Fixed seed, so running it
again produces the same files.
"""

import csv
import json
import random
from datetime import date, timedelta

from sandbox.paths import TEMPLATES

ROWS = 200
START = date(2026, 1, 1)

# job_id -> config. The three jobs differ on purpose (delimiter, date format).
JOBS = {
    "load_orders": {
        "source_path": "data/orders.csv", "delimiter": ",",
        "columns": ["order_id", "customer_id", "amount", "order_date"],
        "date_column": "order_date", "date_format": "%Y-%m-%d",
        "batch_size": 100, "timeout_seconds": 30, "target_table": "orders",
    },
    "load_customers": {
        "source_path": "data/customers.csv", "delimiter": ",",
        "columns": ["customer_id", "name", "country", "signup_date"],
        "date_column": "signup_date", "date_format": "%Y-%m-%d",
        "batch_size": 50, "timeout_seconds": 60, "target_table": "customers",
    },
    "load_events": {
        "source_path": "data/events.csv", "delimiter": ";",
        "columns": ["event_id", "customer_id", "event_type", "event_date"],
        "date_column": "event_date", "date_format": "%d/%m/%Y",
        "batch_size": 200, "timeout_seconds": 20, "target_table": "events",
    },
}


def make_row(job_id: str, n: int, rng: random.Random) -> list:
    day = START + timedelta(days=rng.randrange(300))
    customer = f"C{rng.randrange(1, 80):03d}"
    if job_id == "load_orders":
        return [f"O{n:04d}", customer, f"{rng.uniform(5, 500):.2f}", day.strftime("%Y-%m-%d")]
    if job_id == "load_customers":
        country = rng.choice(["TN", "FR", "DE", "IT", "MA"])
        return [f"C{n:03d}", f"Customer {n}", country, day.strftime("%Y-%m-%d")]
    event = rng.choice(["view", "click", "purchase", "refund"])
    return [f"E{n:04d}", customer, event, day.strftime("%d/%m/%Y")]


def main() -> None:
    rng = random.Random(496)
    (TEMPLATES / "jobs").mkdir(parents=True, exist_ok=True)
    (TEMPLATES / "data").mkdir(parents=True, exist_ok=True)
    for job_id, config in JOBS.items():
        job_path = TEMPLATES / "jobs" / f"{job_id}.json"
        job_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        with (TEMPLATES / config["source_path"]).open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=config["delimiter"], lineterminator="\n")
            writer.writerow(config["columns"])
            for n in range(1, ROWS + 1):
                writer.writerow(make_row(job_id, n, rng))


if __name__ == "__main__":
    main()
