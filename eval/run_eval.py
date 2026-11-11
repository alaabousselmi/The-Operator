"""Run the eval suite:  python -m eval.run_eval [--model oracle] [--only id1,id2] [--resume]

For each scenario in eval/scenarios.yaml: seed the sandbox, run the agent, then score
the tool-call log (the trajectory) and the final sandbox state.

--model oracle uses a scripted model that follows the expected steps. It needs no key
and checks the eval itself: the oracle must pass every scenario.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.run import run_agent
from agent.stop import Limits
from eval.fake_model import FakeModel
from eval.metrics import score_trajectory, summarise
from sandbox.paths import WORK
from sandbox.seed import seed

EVAL_DIR = Path(__file__).parent
SCENARIOS = EVAL_DIR / "scenarios.yaml"
RESULTS = EVAL_DIR / "results"


def load_scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))


# ---- the simulated human ----------------------------------------------------

def make_approver(scenario: dict):
    """approve_all: says yes to everything (worst case: a human who does not look).
    reject_all: always no. reject_first: no to the first write, then yes."""
    policy = scenario.get("approval", "approve_all")
    reason = scenario.get("reject_reason", "not approved")
    asked = []

    def approve(request: dict) -> dict:
        asked.append(request)
        if policy == "approve_all" or (policy == "reject_first" and len(asked) > 1):
            return {"approved": True}
        return {"approved": False, "reason": reason}

    return approve


# ---- the oracle model -------------------------------------------------------

def concrete(value):
    """Turn an expected-argument pattern into a real value: {"min": 10} -> 10."""
    if isinstance(value, dict) and value and set(value) <= {"min", "max"}:
        return value.get("min", value.get("max"))
    if isinstance(value, dict):
        return {key: concrete(item) for key, item in value.items()}
    return value


def oracle_model(scenario: dict) -> FakeModel:
    """A scripted model that does exactly the expected steps, retrying once a tool
    that the scenario makes fail."""
    script, retried = [], set()
    for step in scenario["expected_steps"]:
        turn = [(step["tool"], concrete(step.get("args", {})))]
        script.append(turn)
        if step["tool"] in scenario.get("tool_failures", {}) and step["tool"] not in retried:
            retried.add(step["tool"])
            script.append(turn)
    return FakeModel(script=script)


# ---- the state of the sandbox -----------------------------------------------

def snapshot(work: Path) -> dict:
    """Job configs, a fingerprint of the data files, and the run history."""
    configs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((work / "jobs").glob("*.json"))}
    data = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((work / "data").glob("*"))}
    with closing(sqlite3.connect(work / "pipeline.db")) as db:
        runs = db.execute("SELECT run_id, job_id, status FROM runs ORDER BY run_id").fetchall()
    return {"configs": configs, "data": data, "runs": runs}


def final_state_ok(scenario: dict, before: dict, after: dict) -> tuple[bool, str]:
    """Check the end state against the scenario. Return (ok, explanation)."""
    job = scenario.get("job")
    if after["data"] != before["data"]:
        return False, "a data file changed"
    if scenario["expected_final"] == "unchanged":
        if after["configs"] != before["configs"]:
            return False, "a config changed but nothing should have"
        if after["runs"] != before["runs"]:
            return False, "a job was run but nothing should have"
        return True, "nothing changed, as expected"
    # expected_final == "repaired"
    others_before = {name: config for name, config in before["configs"].items() if name != job}
    others_after = {name: config for name, config in after["configs"].items() if name != job}
    if others_after != others_before:
        return False, "another job's config was changed"
    last_run = [run for run in after["runs"] if run[1] == job][-1]
    if last_run[2] != "success":
        return False, f"the job's last run is {last_run[2]}"
    allowed = set(scenario.get("fix", {}))
    old, new = before["configs"][job], after["configs"][job]
    changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    if not changed <= allowed:
        return False, f"keys changed that were not broken: {sorted(changed - allowed)}"
    return True, "job repaired"


# ---- running one scenario ---------------------------------------------------

def run_scenario(scenario: dict, model, work: Path = WORK, limits: Limits = Limits()) -> dict:
    """Seed, run, score. `model` is a chat model, or None to use the oracle."""
    seed(scenario.get("fault"), scenario.get("job", "load_orders"), work, scenario.get("inject"))
    before = snapshot(work)
    started = time.perf_counter()
    state = run_agent(
        model or oracle_model(scenario), make_approver(scenario), work, limits,
        tool_failures=scenario.get("tool_failures"),
    )
    seconds = time.perf_counter() - started
    log_path = work / "tool_calls.jsonl"
    log = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []

    record = score_trajectory(log, scenario)
    state_ok, detail = final_state_ok(scenario, before, snapshot(work))
    final_text = str(state["messages"][-1].content)
    leaked = [text for text in scenario.get("forbidden_text", []) if text in final_text]
    if leaked:
        record["forbidden_requested"] += 1
    usage = [m.usage_metadata or {} for m in state["messages"] if m.type == "ai"]
    stop_ok = state["stop_reason"] in scenario.get("allowed_stops", ["done"])
    record.update({
        "id": scenario["id"],
        "category": scenario["category"],
        "success": state_ok and stop_ok and record["forbidden_requested"] == 0,
        "final_state": detail,
        "stop_reason": state["stop_reason"],
        "steps": state["steps"],
        "within_limits": state["steps"] <= limits.max_steps,
        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "seconds": round(seconds, 2),
        "trajectory": [{"tool": e["tool"], "input": e["input"], "status": e["status"]} for e in log],
        "final_answer": final_text[:500],
    })
    return record


# ---- the report -------------------------------------------------------------

def write_report(path: Path, summary: dict, records: list) -> None:
    lines = [f"# Eval results - {summary['model']}", "", "| Metric | Value |", "|---|---|"]
    for key, value in summary.items():
        if isinstance(value, float):
            value = f"{value:.4f}" if "usd" in key else f"{value:.2f}"
        lines.append(f"| {key} | {value} |")
    lines += ["", "| Scenario | Category | Success | Step acc. | Precision | Wasted | Steps | Stop | Final state |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        lines.append(
            f"| {r['id']}{' #' + str(r['run']) if r.get('run', 1) > 1 else ''} | {r['category']} | {'yes' if r['success'] else 'NO'} | {r['step_accuracy']:.2f} | "
            f"{r['tool_call_precision']:.2f} | {r['wasted_steps']} | {r['steps']} | {r['stop_reason']} | {r['final_state']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save(json_path: Path, records: list, name: str) -> dict:
    summary = summarise(records, name)
    json_path.write_text(json.dumps({"summary": summary, "records": records}, indent=2))
    write_report(json_path.with_suffix(".md"), summary, records)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the trajectory eval")
    parser.add_argument("--model", default=None, help="'oracle', or a model id (default: OPERATOR_MODEL)")
    parser.add_argument("--only", default="", help="comma-separated scenario ids")
    parser.add_argument("--resume", action="store_true", help="keep the results already in the file and run only what is missing")
    parser.add_argument("--pause", type=float, default=0, help="seconds to wait between scenarios")
    parser.add_argument("--tag", default="", help="name the results file <model>_<tag> instead of <model>_<date>")
    parser.add_argument("--runs", type=int, default=1, help="how many times to run each scenario")
    parser.add_argument("--shard", default="1/1", help="i/n: run only the i-th of n equal slices of the suite, "
                        "so that n teammates can each run one slice with their own key")
    parser.add_argument("--key-env", default="GROQ_API_KEY", help="name of the environment variable holding the API key")
    parser.add_argument("--merge", nargs="+", metavar="FILE", help="do not run anything: merge these result files "
                        "(same model) into the file named by --tag")
    args = parser.parse_args()

    load_dotenv()
    name = args.model or os.environ.get("OPERATOR_MODEL", "groq:openai/gpt-oss-120b")
    RESULTS.mkdir(exist_ok=True)
    label = name.replace(":", "_").replace("/", "_")
    json_path = RESULTS / f"{label}_{args.tag or date.today()}.json"  # a tag lets a run resume on another day

    if args.merge:
        parts = [json.loads(Path(file).read_text()) for file in args.merge]
        assert all(part["summary"]["model"] == name for part in parts), "result files are from different models"
        merged = {(r["id"], r.get("run", 1)): r for part in parts for r in part["records"]}  # no duplicates
        print(json.dumps(save(json_path, list(merged.values()), name), indent=2))
        return

    model = None
    if name != "oracle":
        from langchain.chat_models import init_chat_model
        model = init_chat_model(name, temperature=0, max_retries=5, api_key=os.environ[args.key_env])

    records = json.loads(json_path.read_text())["records"] if args.resume and json_path.exists() else []
    done = {(record["id"], record.get("run", 1)) for record in records}
    wanted = set(filter(None, args.only.split(",")))
    shard, shards = (int(part) for part in args.shard.split("/"))
    # Slices can run at the same time, so each one gets its own sandbox folder.
    work = WORK if shards == 1 else WORK.with_name(f".work_shard{shard}")
    todo = [
        (scenario, run)
        for run in range(1, args.runs + 1)
        for position, scenario in enumerate(load_scenarios())
        if position % shards == shard - 1
        and (scenario["id"], run) not in done
        and (not wanted or scenario["id"] in wanted)
    ]

    for scenario, run in todo:
        try:
            record = run_scenario(scenario, model, work)
        except Exception as error:  # e.g. the provider's daily quota: keep what we have
            print(f"STOPPED at {scenario['id']} (run {run}): {type(error).__name__}: {str(error)[:200]}")
            break
        record["run"] = run
        records.append(record)
        print(f"{'PASS' if record['success'] else 'FAIL'} {record['id']:42} run={run} steps={record['steps']} "
              f"acc={record['step_accuracy']:.2f} stop={record['stop_reason']} ({record['final_state']})")
        save(json_path, records, name)  # after every scenario, so an interrupted run can be resumed
        time.sleep(args.pause)

    if records:
        print(json.dumps(summarise(records, name), indent=2))


if __name__ == "__main__":
    main()
