"""Run the eval in parallel, one slice per API key:

    python -m eval.run_team --tag v3 --runs 3 --once repair

Looks for GROQ_API_KEY and GROQ_API_KEY_1 ... GROQ_API_KEY_9 in the environment (.env).
Works in rounds: the remaining work is cut into one slice per usable key, the slices
run at the same time (each key has its own sandbox folder and results file), and the
results are merged. A key that hits its daily quota is left out of the next round, so
its unfinished slice is shared among the other keys. Running the same command again
later continues from the merged results.

Keys stay in .env, which is git-ignored. Never commit or print a key.
"""

import argparse
import json
import os
import subprocess
import sys

from dotenv import load_dotenv

from eval.run_eval import RESULTS, plan

MAX_ROUNDS = 4


def find_keys() -> list[str]:
    """Names of the environment variables that hold distinct API keys."""
    names, seen = [], set()
    for name in ["GROQ_API_KEY"] + [f"GROQ_API_KEY_{n}" for n in range(1, 10)]:
        value = os.environ.get(name)
        if value and value not in seen:  # skip empty names and a key written under two names
            names.append(name)
            seen.add(value)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the eval in parallel slices, one per API key")
    parser.add_argument("--tag", required=True, help="name of this eval run, e.g. v3")
    parser.add_argument("--runs", type=int, default=1, help="how many times to run each scenario")
    parser.add_argument("--once", default="", help="comma-separated categories to run only once")
    parser.add_argument("--pause", default="8", help="seconds to wait between scenarios in each slice")
    args = parser.parse_args()

    load_dotenv()
    model = os.environ.get("OPERATOR_MODEL", "groq:openai/gpt-oss-120b")
    label = model.replace(":", "_").replace("/", "_")
    merged = RESULTS / f"{label}_{args.tag}.json"
    keys = find_keys()
    print(f"{len(keys)} key(s) found", flush=True)

    for round_number in range(1, MAX_ROUNDS + 1):
        # Merge everything done so far (also from earlier days) and see what is left.
        parts = [str(path) for path in sorted(RESULTS.glob(f"{label}_{args.tag}_key*.json"))]
        done = set()
        if parts:
            subprocess.run([sys.executable, "-m", "eval.run_eval", "--model", model, "--tag", args.tag,
                            "--merge", *parts], stdout=subprocess.DEVNULL, check=True)
            done = {(r["id"], r.get("run", 1)) for r in json.loads(merged.read_text())["records"]}
        left = len(plan(args.runs, set(filter(None, args.once.split(","))), set(), done))
        print(f"round {round_number}: {len(done)} run(s) done, {left} left, {len(keys)} usable key(s)", flush=True)
        if left == 0 or not keys:
            break

        slices = []
        for number, key_name in enumerate(keys, start=1):
            command = [
                sys.executable, "-m", "eval.run_eval", "--model", model, "--resume",
                "--tag", f"{args.tag}_key{key_name[-1]}", "--key-env", key_name,
                "--shard", f"{number}/{len(keys)}", "--runs", str(args.runs), "--once", args.once,
                "--pause", args.pause,
            ]
            if done:
                command += ["--done-from", str(merged)]
            log = open(RESULTS / f"{args.tag}_key{key_name[-1]}.log", "a", encoding="utf-8")
            slices.append((key_name, subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)))
        # Exit code 2 = stopped by an error such as the daily quota: do not use that key again today.
        keys = [key_name for key_name, process in slices if process.wait() == 0]

    if merged.exists():
        print(json.dumps(json.loads(merged.read_text())["summary"], indent=2))


if __name__ == "__main__":
    main()
