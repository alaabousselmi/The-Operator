# Tasks — Data Pipeline Repair Agent (CS496 Project 3, "The Operator")

Source brief: `project3-operator.pdf` (local only, not committed).
Grading: Works 30% · Safe 30% · Measured 25%. Deadline: repo frozen before first session of Week 13 (demo includes a live injection attempt).

Rules for every task:
- LangGraph is mandatory for the loop. Read the linked doc page before using any API; do not guess.
- Update `Progress.md` after each task (status, decisions, gotchas). Tick the box here.
- One commit per task, pushed to GitHub. No credentials in the repo (`.env` is git-ignored).
- Every line must be explainable at the demo: keep code small and plain.
- Every technical choice gets an entry in `DECISIONS.md` (choice, why, rejected, revisit-if) before code depends on it.

## 1. What we are building

An agent that **finds a failed pipeline job, reads its logs, diagnoses the cause, fixes the job config, and re-runs it** — inside a resettable sandbox, with a human approving every write.

- Sandbox = a local mini pipeline: jobs defined by JSON configs, a real runner that loads CSV into SQLite, run history and log files. Failures are real (the runner actually fails), not hard-coded strings.
- Writes = `update_job_config` and `rerun_job`. Both idempotent, both behind the human checkpoint.
- Attack surface = log text, config values and CSV contents (all returned by tools).

## 2. Verified LangGraph facts (langgraph 1.2.x, Python >= 3.10, checked 2026-11-11)

| Need | API |
|---|---|
| Graph | `from langgraph.graph import StateGraph, START, END, MessagesState`; reducer `from langgraph.graph.message import add_messages` |
| Tool execution | `from langgraph.prebuilt import ToolNode`; router = hand-written `should_continue` + `add_conditional_edges` |
| Tools | `from langchain.tools import tool`; `@tool(args_schema=PydanticModel)` |
| Model | `from langchain.chat_models import init_chat_model`; tokens in `response.usage_metadata` (may be None) |
| Human checkpoint | `from langgraph.types import interrupt, Command`; payload returned in `result["__interrupt__"]`; resume with `graph.invoke(Command(resume=...), config)` |
| Persistence | needs checkpointer + `{"configurable": {"thread_id": ...}}`; `from langgraph.checkpoint.memory import InMemorySaver`; SQLite: `pip install langgraph-checkpoint-sqlite`, `from langgraph.checkpoint.sqlite import SqliteSaver` |
| Hard stop | top-level config key `recursion_limit` (default ~10 000, so we MUST set it); raises `from langgraph.errors import GraphRecursionError` |
| Graceful stop | own `steps` counter in state (DECISIONS D6); `RemainingSteps` exists but is not used |

Gotchas: on resume the interrupted node **re-runs from its start** → no side effects before `interrupt()`, never wrap `interrupt()` in bare try/except. `ToolNode(handle_tool_errors=...)` exists, but we catch errors in our own tool wrapper so logging and formatting live in one place (T3).

Docs: https://docs.langchain.com/oss/python/langgraph/overview (pages: interrupts, persistence, graph-api, errors/GRAPH_RECURSION_LIMIT).

## 3. Target repo layout

```
README.md  errors.md  threat_model.md  postmortem.md  report.pdf
Tasks.md  Progress.md  DECISIONS.md  pyproject.toml  .env.example  .gitignore
agent/    state.py  tools.py  calls.py  graph.py  stop.py  checkpoint.py  prompts.py  run.py  cli.py
sandbox/  paths.py  runner.py  seed.py  reset.py  faults.py  make_templates.py  templates/   (runtime data in sandbox/.work/, git-ignored)
eval/     scenarios.yaml  run_eval.py  metrics.py  fake_model.py  results/
tests/    test_stop.py  test_sandbox.py  test_tools.py  test_checkpoint.py  test_eval.py  test_errors.py  test_injection.py
```

## 4. Tasks

### Phase 0 — Setup
- [x] **T0.1** Read brief, write `Tasks.md` + `Progress.md`, `git init`, first commit.
- [x] **T0.2** Create GitHub repo and push (`origin` = github.com/alaabousselmi/The-Operator).
- [x] **T0.3** LLM chosen: Groq `openai/gpt-oss-120b` for v1, paid model compared later (DECISIONS.md D2). Model read from env `OPERATOR_MODEL`.
- [x] **T0.4** `pyproject.toml` with pinned deps, `.gitignore`, `.env.example`, empty packages. Setup command: `pip install -e .`. Topic approved by instructor.
- [ ] **T0.5** (user) Create a Groq API key, put it in `.env`, and note the real free-tier limits from the Groq console Limits page in DECISIONS.md D2. Needed before T5.5 only.

### Phase 1 — Stop rule first (brief: "Write the stopping condition first")
- [x] **T1.1** `agent/state.py`: `AgentState` = messages (`add_messages`), `steps` (model calls), `tokens_used`, `stop_reason`.
- [x] **T1.2** `agent/stop.py`: `Limits(max_steps, max_tokens)`, `stop_reason(state, limits)`, `hard_recursion_limit`. `agent/graph.py`: `build_graph(model, tools, limits, checkpointer)` with nodes `llm`, `tools`, `finalize` and `run_config(limits, thread_id)`.
- [x] **T1.3** `eval/fake_model.py`: `FakeModel(script=[[(tool, args)]], loop_forever, tokens_per_call)`.
- [x] **T1.4** `tests/test_stop.py` = **the proof** (8 tests): looping model stopped at exactly `max_steps` calls; stopped by token budget; `GraphRecursionError` when graceful rules are disabled.

### Phase 2 — Sandbox
- [x] **T2.1** `sandbox/runner.py`: `run_job(job_id, work)` loads CSV → SQLite (replace mode), records a row in `runs` (run_id, job_id, status, error_code, rows_loaded, config_hash, times) and writes `logs/<run_id>.log`. Helpers: `load_config`, `config_hash`, `check_config`, `connect`. Errors are `JobError(code, message)`.
- [x] **T2.2** `sandbox/faults.py`: `FAULTS[name] = (function, error_code, fixable)`. Fixable: `wrong_path`, `wrong_delimiter`, `renamed_column`, `bad_date_format`, `batch_too_large`, `timeout_too_low`, `missing_key`. Not fixable (escalate): `corrupt_source`, `source_deleted`.
- [x] **T2.3** `sandbox/reset.py` (`python -m sandbox.reset`) and `sandbox/seed.py` (`python -m sandbox.seed <fault> [job_id]`, returns the failed run). Jobs: `load_orders`, `load_customers`, `load_events` (templates from `sandbox/make_templates.py`). Path jail: `sandbox/paths.py::resolve_inside`.
- [x] **T2.4** `tests/test_sandbox.py` (32 tests): every fault fails every job with its code; reset restores identical state; rerun does not duplicate rows; reset refuses non-sandbox folders; paths cannot escape.

### Phase 3 — Tools (`agent/tools.py`, `agent/calls.py`)
- [x] **T3.1** Read tools: `list_failed_runs()`, `list_job_runs(job_id)`, `get_run_logs(run_id, tail_lines≤200)`, `get_job_config(job_id)`, `validate_config(job_id, changes)` (dry run). Built by `make_tools(work)`; strict pydantic schemas (`extra="forbid"`, id patterns, bounded values).
- [x] **T3.2** Write tool `update_job_config(job_id, changes)`: only the 8 typed config keys; `target_table` can be added but not changed; backs up the old config; same values → `no_change`.
- [x] **T3.3** Write tool `rerun_job(job_id)`: idempotency key derived from (job, config hash); unchanged config → returns the existing run (`already_ran: true`).
- [x] **T3.4** Deliberately absent: no delete tool, no shell tool, no free-path file tool. `WRITE_TOOLS` lists the tools that need approval.
- [x] **T3.5** `agent/calls.py::make_tool_node(tools, log_path)`: `ToolNode` with `handle_tool_errors=format_error` (one-line `ERROR <CODE>: ...` text) and `wrap_tool_call` logging to `tool_calls.jsonl`. `tests/test_tools.py` (20 tests): full repair path, 13 bad calls rejected with no state change, both writes idempotent, every call logged.

### Phase 4 — Loop + human checkpoint
- [x] **T4.1** `agent/graph.py`: `build_graph(model, work, limits, checkpointer, tools=None, tool_failures=None)`; nodes `llm` → router → `approval` (writes) / `tools` (reads) / `finalize`. Single agent, ReAct.
- [x] **T4.2** `agent/checkpoint.py`: `approval` node shows a diff via `interrupt()`; only `{"approved": True}` passes; a rejection goes back to the model as a tool result with the reason and is logged as `rejected`.
- [x] **T4.3** `agent/prompts.py`: `SYSTEM_PROMPT`, `TASK`, `as_data` (wraps tool results in `<tool_output>`, defuses closing tags).
- [x] **T4.4** `agent/run.py::run_agent(model, approve, work, limits, checkpointer, tool_failures, on_message)` and `agent/cli.py`: `python -m agent.cli --scenario <fault> [--job J] [--no-seed] [--auto-approve]`.
- [x] **T4.5** `tests/test_checkpoint.py` (10 tests): reads pass, writes wait; approve = exactly one write; anything but an explicit yes blocks; paused run survives a restart (SQLite); user changes mind mid-repair.
- [x] **T4.6** Loop/retry rule `max_repeats=3` in `agent/stop.py` (stop reason `loop`); stop by limit after a partial repair reports the writes done; old configs stay in `backups/`.

### Phase 5 — Eval (`eval/`)
- [x] **T5.1** `eval/scenarios.yaml`: fields documented in the file header.
- [x] **T5.2** 37 scenarios: 14 repair, 5 tool_failure, 1 tool_failure_persistent, 4 no_fix, 2 human_reject, 11 injection.
- [x] **T5.3** `eval/metrics.py`: `matches`, `score_trajectory`, `summarise`, `PRICES`.
- [x] **T5.4** `eval/run_eval.py`: `python -m eval.run_eval [--model oracle|<id>] [--only ids] [--resume] [--pause s] [--tag name] [--runs n] [--shard i/n] [--merge files]` → `eval/results/<model>_<tag or date>.json` + `.md`. `tests/test_eval.py`: oracle passes all 32; bad agents fail.
- [x] **T5.5** Full eval on Groq `openai/gpt-oss-120b` (2026-11-11): 32/32 success, results in `eval/results/groq_openai_gpt-oss-120b_v1.{json,md}`.
- [x] **T5.7** Harder, repeated eval (2026-11-11): 37 scenarios (11 injections), 83 runs on 120b via `python -m eval.run_team --tag v3 --runs 3 --once repair` with 6 keys. 80/83; the decoy-file injection executed 3/3 → routing-key rule (DECISIONS D8c) → re-run of affected cases passes (`*_v3_after_fix_{a,b}.json`). Documents updated. Still not written: a two-jobs-failing scenario.

### Phase 6 — Error taxonomy (`errors.md`)
- [x] **T6.1** `errors.md`: 11 classes (tool down once / for good, bad arguments, empty result, wrong tool, loop, timeout, user changes mind, partial failure, unfixable fault, over-fixing), each with system behaviour, a named test and eval scenarios; error-code table; recovery table; what is not handled.
- [x] **T6.2** `tests/test_errors.py` (15 tests), one or more per class.

### Phase 7 — Threat model (`threat_model.md`)
- [x] **T7.1** `threat_model.md`: assets, trust, 5 entry points, 7 attacker goals, 10 defences (hard vs soft), goal → defence table, residual risks, demo checklist.
- [x] **T7.2** 7 injection scenarios in the eval + `tests/test_injection.py` (obedient-model tests of the checkpoint and of the tool rules). Results and the one attack that worked are reported in `threat_model.md` §6.
- [x] **T7.3** Demo rehearsed once with a new, plausible injection: it partly worked → minimal-repair rule added (DECISIONS D8b), scenario 7 added.
- [x] **T7.4** Superseded by the v3 run (all 11 injection cases, 3 runs each, on 120b).
- [x] **T7.5** Routing keys restricted to last known-good value (done, D8c). Not done: strip terminal control characters before printing tool output in the CLI (threat model risk 6).

### Phase 8 — Hand-in
- [x] **T8.1** `README.md`: setup command, run command, results table with caveats, repo map. **Contributions table still has "to fill in" per member (user).**
- [x] **T8.2** `report.md` → `report.pdf` (3 pages, max 4) built by `tools/build_report.py` (needs `pip install reportlab`, not a project dependency).
- [x] **T8.3** `postmortem.md`: 7 problem groups with lessons, what we would do differently, what is still open.
- [x] **T8.4** Clean-clone test (fresh clone, new venv, `pip install -e .`, `pytest`, oracle eval) and secret scan. `.gitattributes` forces LF and marks PDFs binary.
- [ ] **T8.5** Before freezing: Contributions filled (user), re-run the clean-clone test, tag the commit.

### Phase 9 — LangGraph highlight and LangSmith (course requirement, added 2026-11-11)
- [x] **T9.1** README: graph diagram generated from the compiled graph + table of the LangGraph features used and where.
- [x] **T9.2** `agent/tracing.py`: `traced_run` (one LangSmith trace per run) and `log_scores` (eval scores as feedback); wired into `eval/run_eval.py::run_scenario` and `agent/cli.py`; `.env.example` variables; `tests/conftest.py` forces tracing off; `langsmith==0.14.17` pinned. Checked offline with a local capture server.
- [ ] **T9.3** (user) Create a LangSmith account and API key, add `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=the-operator` to `.env` (EU accounts: also `LANGSMITH_ENDPOINT`).
- [ ] **T9.4** Verify with the real key: `python -m eval.run_eval --only repair_bad_date_format_orders --tag ls_check --key-env GROQ_API_KEY_2`, then check in the UI: one trace, nodes visible, 5 feedback scores. Fix `log_scores` if the feedback call is refused. Add 2-3 screenshots to the README/report and prepare one trace (the decoy injection) for the demo.

## 4b. Next week (plan agreed 2026-11-11)

Goal: freeze a repo whose numbers match its code, and a team that can explain every line.

- [ ] **N1 — Freeze the code** (day 1). No more changes to `agent/` or `sandbox/` after this, except bug fixes that force a new eval run.
- [ ] **N2 — Final eval on the frozen code, with LangSmith tracing on** (day 1-2, needs the 6 keys' daily quota and T9.3-T9.4 done): `python -m eval.run_team --tag v4 --runs 3 --once repair` (~865K tokens, ~11 min). Then replace the v3 numbers in `README.md`, `report.md` (+ `python tools/build_report.py`), `threat_model.md` section 6, `errors.md` recovery table. Check for every injection pass that the planted text was actually read.
- [ ] **N3 — Each member reviews their area** (days 1-3, see README Contributions): read every file of the area, run its tests, run `python -m agent.cli` once, and write down anything they cannot explain. Fix or simplify what nobody can explain.
- [ ] **N4 — Demo rehearsal** (day 3-4): follow `threat_model.md` section 8 twice, with one member playing the instructor and inventing a new injection each time (log, config, data file, extra file in `data/`). No `--auto-approve`. Record what happened; a new successful attack means a fix, then N2 again.
- [ ] **N5 — Optional, only if N1-N4 are done**: two-jobs-failing scenario; strip terminal control characters in the CLI output (threat model risk 6); paid-model comparison (T5.6); make the poisoned-old-log case force the agent to read the old log.
- [ ] **N6 — Hand-in** (last day before Week 13): clean-clone test (fresh clone, new venv, `pip install -e .`, `pytest`, `python -m eval.run_eval --model oracle`), check `report.pdf` is at most 4 pages, secret scan, tag the commit, stop pushing.

## 5. Order and dependencies

T0 → T1 (stop rule) → T2 (sandbox) → T3 (tools) → T4 (loop) → T5 (eval) → T6, T7 (can overlap with T5) → T8.
Phases 1–4 + tests need no API key (fake model). A key is first needed at T5.5.
