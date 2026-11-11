"""Run the eval in parallel, one slice per API key:  python -m eval.run_team --tag v3 --runs 3

Looks for GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ... in the environment (.env),
starts one `eval.run_eval --shard i/n` process per key, waits, then merges the slices.
Each slice has its own sandbox folder and its own results file, so a slice stopped by
its daily quota is resumed by running the same command again.

Keys stay in .env, which is git-ignored. Never commit or print a key.
"""

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

from eval.run_eval import RESULTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the eval in parallel slices, one per API key")
    parser.add_argument("--tag", required=True, help="name of this eval run, e.g. v3")
    parser.add_argument("--runs", type=int, default=1, help="how many times to run each scenario")
    parser.add_argument("--pause", default="8", help="seconds to wait between scenarios in each slice")
    args = parser.parse_args()

    load_dotenv()
    model = os.environ.get("OPERATOR_MODEL", "groq:openai/gpt-oss-120b")
    key_names = ["GROQ_API_KEY"] + [f"GROQ_API_KEY_{n}" for n in range(2, 10)]
    key_names = [name for name in key_names if os.environ.get(name)]
    count = len(key_names)
    print(f"{count} key(s) found: {count} slice(s), {args.runs} run(s) per scenario")

    slices = []
    for number, key_name in enumerate(key_names, start=1):
        command = [
            sys.executable, "-m", "eval.run_eval", "--model", model, "--resume",
            "--tag", f"{args.tag}_part{number}", "--shard", f"{number}/{count}",
            "--runs", str(args.runs), "--pause", args.pause, "--key-env", key_name,
        ]
        log = open(RESULTS / f"{args.tag}_part{number}.log", "w", encoding="utf-8")
        slices.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
    for process in slices:
        process.wait()

    label = model.replace(":", "_").replace("/", "_")
    parts = [str(path) for path in sorted(RESULTS.glob(f"{label}_{args.tag}_part*.json"))]
    subprocess.run([sys.executable, "-m", "eval.run_eval", "--model", model, "--tag", args.tag, "--merge", *parts])


if __name__ == "__main__":
    main()
