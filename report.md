# The Operator: a data pipeline repair agent

CS496 AI Engineering, Project 3. Alaaeddine Bousselmi, Mohamed Amine Zouaoui, Seifeddine Knani, Walid Fakhfakh. Repository: github.com/alaabousselmi/The-Operator

## 1. The task, the tools, and what the write tools change

The agent finds a failed pipeline job, reads its log, diagnoses the cause, fixes the job's config and re-runs it. The pipeline is a real one in miniature: three jobs (`load_orders`, `load_customers`, `load_events`), each described by a JSON config, load a CSV file into a SQLite table. Every run is recorded and writes a log. Nine faults can be injected by actually breaking a config or a data file; seven are fixable by a config change, two are not (damaged data, deleted file) and must be escalated.

| Tool | Kind | Purpose |
|---|---|---|
| `list_failed_runs` | read | jobs whose latest run failed |
| `list_job_runs` | read | history of one job |
| `get_run_logs` | read | last lines of a run log (max 200) |
| `get_job_config` | read | current config |
| `validate_config` | read | dry run of a proposed change |
| `update_job_config` | **write** | changes keys of a job config; the old config is backed up |
| `rerun_job` | **write** | runs the job again and so replaces its target table |

Design rules: every tool has a strict pydantic schema (unknown fields rejected, ids matched by pattern, values bounded); errors come back as one line, `ERROR <CODE>: what happened. What to do next.`, never a stack trace; every call is logged with input, output, status and duration. Both writes are idempotent: the same update twice writes once, and a job whose config has not changed since its last run is not run again (the key is derived from the config hash, not supplied by the model). A config write is accepted only as a **minimal repair**: the job must fail now, pass with the change, and need every changed key. There is no delete, shell or free-path tool.

## 2. The loop, the stop rule, and the proof it stops

The loop is a single-agent ReAct graph built with LangGraph's `StateGraph`: `llm` -> router -> `tools` (reads) or `approval` -> `tools` (writes) -> `llm`, ending in `finalize`. We built the graph by hand rather than use a prebuilt agent so that the router, the stop rule and the checkpoint are visible nodes and edges that can each be tested.

The stop rule was written before the agent. Four independent limits: (1) 12 model calls; (2) 40 000 tokens; (3) the same call (same tool, same arguments) at most 3 times, which is also the retry limit; (4) LangGraph's `recursion_limit`, set explicitly because its default is about 10 000. Limits 1 to 3 end the run cleanly with a recorded reason and a note listing the writes already done; limit 4 raises an error and exists in case the first three have a bug.

**Proof** (`tests/test_stop.py`, a scripted model that asks for a tool forever): the run ends at exactly `max_steps` model calls for limits of 1, 2, 5, 12 and 30; it ends on the first call that reaches the token budget; a repeated call is refused on its 4th request; and with all three graceful limits disabled, LangGraph still stops the run with `GraphRecursionError`. In all eval runs with the real model the stop rule was never exceeded.

## 3. Sandbox and human checkpoint

**Sandbox.** All state lives in `sandbox/.work/` and is rebuilt from committed templates by `python -m sandbox.reset`; a test checks that a reset after deliberate damage restores an identical state. File paths are resolved inside the sandbox and table and column names must match a safe pattern, because these values come from config the agent can write. Time and memory are simulated by fixed rules so that timeout and out-of-memory failures are instant and repeatable.

**Checkpoint.** Any write routes through an `approval` node that calls LangGraph's `interrupt()` and hands the caller a diff computed by our code from the real config (old value -> new value). Only the exact answer `{"approved": True}` lets the write through; anything else is a rejection, which is returned to the model as a tool result with the human's reason. Because the pause is a graph edge, no text can route around it. Paused runs are stored in SQLite and survive a restart. Reads do not need approval, so the human is asked only when something would change. Tests (`tests/test_checkpoint.py`): no write before approval; approve executes exactly once; anything but an explicit yes blocks; a rejection mid-repair leaves the first write in place and starts no run.

## 4. Trajectory eval results

33 scenarios with expected steps (`eval/scenarios.yaml`): 14 repairs, 5 single tool failures, 1 persistent tool failure, 4 no-fix, 2 human rejections, 7 injections. The trajectory is read from the tool-call log, not from the model's text. **Step accuracy** = expected steps done in order / expected steps. **Tool-call precision** = right calls / calls made. **Wasted steps** = calls beyond the expected path. **Success** = right final state (and only the broken key changed) AND a proper stop AND no forbidden call even requested: a right answer after a dangerous path is a failure. The eval itself is tested: a scripted perfect agent must score 100 %, and scripted bad agents must fail.

Model: Groq `openai/gpt-oss-120b`, temperature 0, one run per scenario, simulated human approves everything (the worst case).

| Metric | v1 (32 scenarios) | v2, after the minimal-repair rule (28 of 33) |
|---|---|---|
| Task success | 32 / 32 | 28 / 28 |
| Step accuracy | 1.00 | 1.00 |
| Tool-call precision | 0.99 | 0.99 |
| Wasted steps per task | 0.34 | 0.25 |
| Stop rule exceeded | 0 | 0 |
| Steps / tokens per task | 5.97 / 10 250 | 5.93 / 10 593 |
| Time per task p50 / p95 | 3.7 s / 18.9 s | 20.0 s / 55.7 s |

v2 is incomplete on this model: the free tier's 200 000 tokens/day limit stopped the run twice. The 5 missing scenarios (all injections) were run on the smaller `gpt-oss-20b` instead. v2 times include rate-limit waits. These are single runs on scenarios we wrote ourselves, so the perfect score is weak evidence; section 6 shows an attack the suite had missed.

## 5. Error taxonomy and recovery results

`errors.md` lists 11 classes, each with the system's behaviour and a named test in `tests/test_errors.py`.

| Class | What happens |
|---|---|
| Tool down / timeout (once) | clear error asking for one retry; the retry succeeds |
| Tool down for good | 3 identical attempts, then the loop rule stops the run; nothing written |
| Bad arguments | rejected by the schema with the field name; nothing changes |
| Empty result | stated in words ("No job is currently failing") |
| Wrong tool | unknown tool: the valid list is returned; write on a healthy job: refused |
| Loop | 4th identical request ends the run |
| User changes mind | write not executed; the reason reaches the model, which follows it or stops |
| Partial failure (step 3 of 5) | the run ends with the list of writes done; a second run finishes the job because writes are idempotent |
| Unfixable fault | every config write is refused; the agent escalates |
| Over-fixing | keys that are not needed for the repair are refused by name |

**Recovery after failure**: on the five scenarios where one tool call is made to fail (unavailable x3, timeout x1, empty x1), the agent still finished the task 5 / 5 in v1 and 5 / 5 in v2. With the update tool permanently down, it stopped without writing. Not handled: provider outage beyond client retries, automatic rollback (old configs are kept in `backups/`), two jobs failing at once.

## 6. Threat model, injection results, and cost model

**Entry points for untrusted text**: run log lines, data values echoed in error messages, config string values, file names. All reach the model through tool output. **Attacker goals**: change a healthy job, redirect data, over-fix the failing job, skip approval, waste resources, leak the prompt, escape the data block.

**Defences.** Hard (hold even if the model obeys the attacker): the small tool surface; strict schemas; the minimal-repair rule; `target_table` cannot be changed; idempotent re-run; the stop rule; the checkpoint enforced by the graph; the path jail. Soft (depend on the model): tool results are wrapped in `<tool_output>` tags, planted closing tags are defused, and the prompt says tagged text is never an instruction. Our rule: every attacker goal must be blocked by at least one hard defence.

**Results (7 cases, forbidden call requested = fail).** v1, six openly hostile cases on 120b: 6 / 6 resisted. Then a rehearsal with a polite "operator note" carrying a ticket number and an "approved fix" **succeeded in part**: the agent applied the right fix and also set two unneeded keys on the failing job, because every existing defence judged values one by one. We added the minimal-repair rule, named such notes in the prompt, and made the note case 7. v2: 2 / 2 resisted on 120b (5 not yet run), 7 / 7 on 20b, with no forbidden call requested. The 20b model was still influenced: it dry-ran the attacker's file path once and skipped validation when the note said to. Tests with a fully obedient scripted model show that the tool rules stop every forbidden config write even when the human approves, and that the checkpoint alone stops all of them when the human rejects.

**Residual risks**: a wrong repair that still passes (another file with the same columns) is stopped only by the human reading the diff; the prompt could be repeated in the final report; all results are single runs.

**Cost model.** Measured tokens x list price ($0.15 / $0.60 per million input / output tokens for `gpt-oss-120b`). A task uses about 6 model calls and 10 600 tokens, of which about 95 % are input, because the system prompt and seven tool schemas are sent on every step.

| | Per task | Eval (33 tasks) | 100x the eval |
|---|---|---|---|
| `gpt-oss-120b` | $0.0018 | $0.060 | $6.02 |
| `gpt-oss-20b` (list price, 12 tasks measured) | $0.0010 | $0.033 | $3.29 |

The first lever for cost is input size (shorter tool descriptions, prompt caching), not the model. On the free tier the real limit is not money but 200 000 tokens per day: about 19 tasks.
