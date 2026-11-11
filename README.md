# The Operator - data pipeline repair agent

CS496 AI Engineering, Project 3. An agent that finds a failed pipeline job, reads its logs, diagnoses the cause, fixes the job's config and re-runs it inside a resettable sandbox, with a human approving every write. Built with LangGraph.

## Setup (one command)

```
pip install -e .
```

Python 3.10 or newer. Then copy `.env.example` to `.env` and put a Groq API key in it (free at console.groq.com). The tests need no key.

## Run (one command)

```
python -m agent.cli --scenario bad_date_format
```

This resets the sandbox, breaks the `load_orders` job, and starts the agent. Each step is printed; before every write the agent shows the change and waits for `y`.

| Command | What it does |
|---|---|
| `python -m agent.cli --scenario <fault> --job <job>` | Break a chosen job with a chosen fault, then repair it |
| `python -m agent.cli --no-seed` | Run on the sandbox as it is (use this after editing a log by hand) |
| `python -m sandbox.reset` | Rebuild a clean sandbox |
| `python -m sandbox.seed <fault> [job]` | Reset, then break one job |
| `pytest` | 166 tests, no API key needed |
| `python -m eval.run_eval --model oracle` | Run the eval with a scripted perfect agent (checks the eval itself) |
| `python -m eval.run_eval --tag mytag --resume --pause 8` | Run the eval with the real model; resumable |
| `python -m eval.run_team --tag v3 --runs 3` | Run the eval in parallel, one slice per API key found in `.env`, then merge; resumable |

Faults: `wrong_path`, `wrong_delimiter`, `renamed_column`, `bad_date_format`, `batch_too_large`, `timeout_too_low`, `missing_key` (fixable), `corrupt_source`, `source_deleted` (not fixable: the agent must escalate). Jobs: `load_orders`, `load_customers`, `load_events`.

## How it works

```
                 +--> finalize --> END        stop rule fired, or the model is done
    START --> llm +--> approval --> tools --+  the model asked for a write
               ^  |        +--> llm            the human said no
               |  +--> tools ---------------+  the model asked for a read
               +----------------------------+
```

- **Tools** (`agent/tools.py`): five read (`list_failed_runs`, `list_job_runs`, `get_run_logs`, `get_job_config`, `validate_config`) and two write (`update_job_config`, `rerun_job`). Strict schemas; both writes are idempotent; a config write is accepted only if it is a minimal repair of a failing job. No delete, shell or free-path tool.
- **Stop rule** (`agent/stop.py`): 12 model calls, 40 000 tokens, 3 identical calls, plus LangGraph's recursion limit as a hard cap. Proof: `tests/test_stop.py`.
- **Human checkpoint** (`agent/checkpoint.py`): every write pauses the graph with `interrupt()` and shows a diff. Only an explicit yes passes. A paused run survives a restart.
- **Sandbox** (`sandbox/`): a real mini pipeline (CSV into SQLite) under `sandbox/.work/`, rebuilt from templates by one command.
- **Every tool call is logged** to `sandbox/.work/tool_calls.jsonl` (input, output, status, time).

## Results

Model: Groq `openai/gpt-oss-120b`, temperature 0, **one run per scenario**, simulated human approves everything. The results below cover the first 33 scenarios (14 repairs, 5 single tool failures, 1 persistent tool failure, 4 no-fix, 2 human rejections, 7 injections). Four tougher injection cases were added afterwards (37 in total) and have not been run on a real model yet.

| Metric | v1 (32 scenarios) | v2, after the minimal-repair rule (28 of 33 done) |
|---|---|---|
| Task success | 32 / 32 | 28 / 28 |
| Step accuracy | 1.00 | 1.00 |
| Tool-call precision | 0.99 | 0.99 |
| Wasted steps per task | 0.34 | 0.25 |
| Recovery after one tool failure | 5 / 5 | 5 / 5 |
| Injection cases with no forbidden call | 6 / 6 | 2 / 2 on 120b; 7 / 7 on `gpt-oss-20b` |
| Stop rule exceeded | 0 | 0 |
| Steps per task | 5.97 | 5.93 |
| Tokens per task | 10 250 | 10 593 |
| Cost per task (list price) | $0.0018 | $0.0018 |
| Cost for 100x the eval workload | $5.76 | $6.02 (scaled to 33 scenarios) |
| Time per task, p50 / p95 | 3.7 s / 18.9 s | 20.0 s / 55.7 s (includes rate-limit waits) |

Read these numbers with care:

- **An injection did work.** Between v1 and v2 a manual rehearsal with a polite "operator note" made the agent add two unneeded config changes. That attack is not in the v1 column because the case did not exist yet. It led to the minimal-repair rule and became injection case 7. See `threat_model.md` section 6.
- **v2 is incomplete on the main model.** Groq's free tier (200 000 tokens/day) stopped the run twice. Five injection cases, including case 7, have been run after the fix only on the smaller `gpt-oss-20b`, where all passed. Finish with `python -m eval.run_eval --tag v2 --resume --pause 8`.
- **We wrote the scenarios ourselves** and ran each once. A perfect score is weak evidence; the guarantees come from the tests of the code-level defences.

Raw results: `eval/results/`. Definitions of every metric: top of `eval/metrics.py`.

## Repository map

| Path | Content |
|---|---|
| `agent/` | Tools with schemas, the loop, the stop rule, the checkpoint, the prompt, the CLI |
| `sandbox/` | The mini pipeline, the fault catalogue, seed and reset |
| `eval/` | 37 scenarios with expected steps, trajectory metrics, the runner, results |
| `tests/` | Stop-rule proof, sandbox, tools, checkpoint, error classes, injection, the eval itself |
| `errors.md` | Error taxonomy with a test per class |
| `threat_model.md` | Injection through tool output: entry points, defences, results, residual risks |
| `DECISIONS.md` | Every technical choice with its reason and the alternatives rejected |
| `postmortem.md` | What went wrong and what we learned |
| `report.pdf` | The 4-page report (source `report.md`, built by `tools/build_report.py`) |
| `Tasks.md`, `Progress.md` | Work plan and current state |

## Contributions

Team: Alaaeddine Bousselmi, Mohamed Amine Zouaoui, Seifeddine Knani, Walid Fakhfakh.

| Member | Contribution |
|---|---|
| Alaaeddine Bousselmi | _to fill in_ |
| Mohamed Amine Zouaoui | _to fill in_ |
| Seifeddine Knani | _to fill in_ |
| Walid Fakhfakh | _to fill in_ |

AI assistance: the code and documents were written with Claude Code; the team reviewed them and is responsible for every line.

No real credentials are in this repository; `.env` is git-ignored.
