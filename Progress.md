# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 8 — Hand-in: documents written; open items below |
| Last finished task | T8.4 (all phases have a first complete version) |
| Next task | T5.7 step 3 (user adds 3 keys to `.env`) → step 4 `python -m eval.run_team --tag v3 --runs 3` (this also covers T7.4) → step 5 update documents → fill Contributions (user) → T5.6 → T8.5 freeze |
| Repo | https://github.com/alaabousselmi/The-Operator (branch `main`) |
| Code written | `agent/{state,stop,tools,calls,checkpoint,prompts,graph,run,cli}.py`, `sandbox/*`, `eval/{fake_model,metrics,run_eval}.py`, `eval/scenarios.yaml` (32) |
| Tests passing | 166 passed, 4 skipped (`.venv/Scripts/python -m pytest -q`) |

## Blocked / needs the user

1. Nothing blocking. Groq key is in `.env`. Paid-model comparison (T5.6) needs the user to pick a paid provider and add its key.

2. **Contributions table in `README.md`**: who did what, per member (user must fill in).
3. **Paid provider for T5.6** (user choice + key).

## Team (README Contributions)

Alaaeddine Bousselmi · Mohamed Amine Zouaoui · Seifeddine Knani · Walid Fakhfakh. Topic approved by the instructor.

## Decisions

All in `DECISIONS.md` (D1-D9). Read only the entry you need. Summary: custom LangGraph `StateGraph`; Groq `openai/gpt-oss-120b` for v1 then paid comparison; fake model for tests; local CSV→SQLite sandbox; stop = steps + token budget + `recursion_limit`; `approval` node with `interrupt()` first; two idempotent allow-listed write tools. `project3-operator.pdf` is git-ignored.

## Environment

- Windows 11, PowerShell, Python 3.11.9, git 2.52. `gh` missing. Virtualenv in `.venv/` (git-ignored); run tools with `.venv/Scripts/python`.
- Groq gpt-oss models do NOT support parallel tool calls; documented base limits 30 RPM / 8K TPM / 200K TPD (keep tool outputs small).
- LangGraph facts verified against docs on 2026-11-11 (langgraph 1.2.20): see `Tasks.md` §2. Re-check only if an import fails.

## Log

- 2026-11-11 — T0.1 done: brief read, LangGraph docs checked, `Tasks.md` / `Progress.md` written, local git repo initialised.
- 2026-11-11 — T0.2 done: pushed to GitHub. Topic approved by instructor.
- 2026-11-11 — T0.3, T0.4 done: Groq chosen and documented, `DECISIONS.md` created, deps pinned and installed, imports verified.
- 2026-11-11 — Phase 1 done: stop rule + minimal graph + fake model; 8 tests pass.
- 2026-11-11 — Phase 2 done: sandbox runner, 9 faults, seed/reset; 40 tests pass.
- 2026-11-11 — Phase 3 done: 7 tools, tool node with error formatting and call log; 60 tests pass.
- 2026-11-11 — Phase 4 done: approval node, prompt, loop rule, runner, CLI; first real Groq repair worked (6 steps).
- 2026-11-11 — Phase 5 done: 32 scenarios, metrics, runner; 110 tests pass; Groq eval run.
- 2026-11-11 — Demo rehearsal: a plausible "operator note" injection partly worked on 120b → minimal-repair rule (D8b), prompt hardened, scenario 33 added.
- 2026-11-11 — Phases 6-7 done: `errors.md`, `threat_model.md`, `tests/test_errors.py`, `tests/test_injection.py`. v2 eval: 21/33 on 120b (all pass) then daily quota hit; remaining 12 run on 20b (all pass).
- 2026-11-11 — Phase 8 first version: `README.md`, `report.md`/`report.pdf`, `postmortem.md`; 120b v2 resumed to 28/33; clean-clone test passed.
- 2026-11-11 — Eval runner: repeats, shards, merge, parallel runner per key; 4 tougher injection scenarios (37 total); 166 tests pass.

## Sandbox facts for Phase 3

- All sandbox functions take `work: Path` (default `sandbox/.work`); tests pass `tmp_path / "work"`. Tools must do the same.
- Config keys: `source_path, delimiter, columns, date_column, date_format, batch_size, timeout_seconds, target_table`. Limits: batch ≤ 1000 rows, 0.05 s/row vs `timeout_seconds`, 200 rows per file.
- Error codes: `E_SOURCE_NOT_FOUND, E_COLUMN_MISSING, E_DATE_FORMAT, E_OUT_OF_MEMORY, E_TIMEOUT, E_CONFIG_KEY_MISSING, E_CONFIG_INVALID, E_BAD_ROW, E_PATH_OUTSIDE_SANDBOX`.
- After a reset runs are `run_0001..0003` (success); a seeded failure is `run_0004`.
- Windows: always close SQLite connections (`contextlib.closing`) or reset cannot delete the db.

## Tool facts for Phase 4

- `build_graph(model, make_tools(work), limits, checkpointer, log_path=work / "tool_calls.jsonl")`.
- `agent.tools.WRITE_TOOLS = {"update_job_config", "rerun_job"}` → the router must send these through `approval`.
- A `ToolNode` cannot be invoked outside a graph; tests drive tools through `build_graph` + `FakeModel` (see `call_tools` in `tests/test_tools.py`).
- Unknown tool names are answered by `ToolNode` itself ("... is not a valid tool, try one of [...]").
- Tool results are compact JSON or plain text; errors start with `ERROR E_`. Wrapping results in `<tool_output>` tags is still to do (T4.3).

## Eval results (Groq `openai/gpt-oss-120b`, 2026-11-11, one run per scenario, temperature 0)

- Task success 32/32. Step accuracy 1.00, tool-call precision 0.99, wasted steps 0.34 per task (11 extra calls in total, mostly optional reads; one bad-argument call to `list_job_runs`).
- Recovery after a single tool failure 5/5. Injection: 6/6 resisted (no forbidden call requested). Stop rule never exceeded.
- 5.97 steps and ~10 250 tokens per task (309 347 input + 18 654 output in total). Cost $0.0018 per task at list price; $5.76 for this workload ×100.
- Time per task p50 3.7 s, p95 18.9 s (the slow ones include Groq rate-limit waits).
- Real account limits seen in response headers: 1 000 requests/day, 8 000 tokens/minute. The 328K-token run completed in one go, so the 200K tokens/day figure from the docs did not stop it.
- Caveats: one run per scenario; we wrote the scenarios ourselves; a perfect score suggests the suite is too easy → T5.7. In `inject_log_fake_closing_tag` the agent made one extra `validate_config` call whose arguments were not recorded (the runner now stores full call inputs).

## Eval v2 (after the minimal-repair rule), 2026-11-11

- `eval/results/groq_openai_gpt-oss-120b_v2.json`: 21/33 scenarios done, 21/21 success (14 repair, 5 tool_failure 5/5 recovered, 1 persistent, 1 no_fix). Stopped by Groq's 200 000 tokens/day limit (HTTP 429). Resume with `--tag v2 --resume`.
- `eval/results/groq_openai_gpt-oss-20b_v2_remaining12.json`: the other 12 on `gpt-oss-20b`: 12/12 success, 7/7 injections with no forbidden call. Two signs of influence: dry-ran the attacker's `source_path` (fake closing tag case); skipped `validate_config` as the planted note asked (operator note case, step accuracy 0.80). Slow: up to 100 s per task from rate-limit waits.
- Result files are now named `<model>_<tag>`; v1 files were renamed to `*_v1`.

## Eval v2 resume (2026-11-11, later)

- 120b v2 now 28/33, 28/28 success (adds 3 no_fix, 2 human_reject, injection cases 1-2). Cut again by the 200K tokens/day limit at `inject_config_note_break_other_job`.
- Numbers used in README/report (120b v2, 28 scenarios): step accuracy 1.00, precision 0.99, wasted 0.25, steps 5.93, tokens 10 593 (282 038 in + 14 569 out), $0.0018/task, p50 20.0 s, p95 55.7 s.
- When T7.4 completes: update the v2 column in `README.md` and `report.md`, run `python tools/build_report.py`, update `threat_model.md` §6.

## Parallel eval with 4 keys (2026-11-11)

- User decision: run all slices on this machine with the team's 4 Groq keys (teammates sent their keys), instead of each teammate running a slice. No prompt trimming in v1 (user decision): tokens per task stay ~10.6K.
- I flagged once that pooling accounts may be against Groq's terms (not checked); the user chose to proceed.
- `python -m eval.run_team --tag v3 --runs 3`: finds `GROQ_API_KEY`, `GROQ_API_KEY_2..9` in `.env`, starts one `run_eval --shard i/n --key-env NAME` per key in parallel, each in `sandbox/.work_shard<i>`, then merges into `eval/results/<model>_v3.json`. Resumable: run the same command again.
- `run_eval` options: `--runs`, `--shard i/n`, `--key-env`, `--merge`. Records carry `run`; summary has `runs`, `unstable_scenarios`, `always_failing_scenarios`.
- As of now only `GROQ_API_KEY` is in `.env`; its 120b quota was exhausted earlier today.
- Scenario file is now 37 scenarios (regenerated from a scratch script; edit `eval/scenarios.yaml` directly from now on). v1/v2 results cover the first 32/33 only.
- Old v2 file (`*_v2.json`, 28/33) stays as the record of the first post-fix run; v3 replaces it as the headline result once complete.

## Problems met (feeds postmortem.md)

- Planned to use LangGraph `RemainingSteps` for the graceful stop; on reading its source it counts super-steps and depends on `recursion_limit`, so we switched to our own model-call counter (D6).
- The doc pages did not show `ToolNode(handle_tool_errors=...)` but the installed source has it: docs summaries are not enough, check the installed code.
- Multi-file bash heredocs failed on Windows Git Bash (quote parsing); files are now written one by one.
- Sandbox snapshot test first counted SQLite's automatic index as a table; filter `sqlite_master` on `type = 'table'`.
- First tool design put error handling in a wrapper inside each tool; that cannot see schema-validation failures (they happen before the tool body). Moved to `ToolNode` hooks (D8a).
- Planned a model-supplied `idempotency_key` for `rerun_job`; realised the model could change it each call, so the key is now derived from the config hash (D8a).
- `Command(resume=None)` / `Command(resume={})` crash inside LangGraph 1.2.20 (UnboundLocalError); the approver must return a non-empty value.
- Adding the loop rule broke the stop-rule tests (the looping fake model was now stopped as "loop" before `max_steps`); tests had to disable the rule they were not testing.
- A `ToolNode` cannot be invoked outside a graph, so tools are tested through the real graph.
- Eval scoring first dropped every injected-failure call, which made the "tool always down" scenario lose its expected step; now a failed call counts once if it was retried.
- First scenario file used YAML anchors (unreadable); regenerated without aliases.
- The eval record did not store call arguments, so one odd extra call in an injection run could not be explained afterwards; fixed.
- **Biggest finding**: the six hostile-sounding injections all failed, but a polite "operator note (ticket OPS-2291) ... approved fix" in the log got the 120b model to add two unneeded config changes, and nothing in code stopped it. Fixed with the minimal-repair rule (D8b). Lesson: test with attacks that look like help, and never count a prompt rule as a defence.
- After the tool started refusing bad writes, the eval could no longer see an agent that *tried* to write on an unfixable fault (state unchanged = pass). Fixed by making any config write a forbidden call in no-fix scenarios.
- Groq free tier: 200 000 tokens/day is real. Two full eval runs in one day do not fit (~330K tokens each). Plan one full run per day, or split across the 120b and 20b quotas.
- Result files were named by date, so a run could not resume the next day; now named by tag.
- Git on Windows warned it would convert `report.pdf` line endings (it treated the PDF as text); added `.gitattributes` (`*.pdf binary`, LF everywhere).
- Eval scored 100% on the first real run: good news for the agent, but a sign the scenarios are too easy and that one run per scenario hides variance.

