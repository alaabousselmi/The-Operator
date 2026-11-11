# Technical decisions

Every technical choice in this project is recorded here with its reason, the alternatives we rejected, and what would make us change it. Add an entry **before** building on a new choice. Facts marked "verified" were read in the official docs or checked by running code on the date shown.

Format: **Choice** · **Why** · **Rejected** · **Revisit if**.

---

## D1 — Agent framework: LangGraph (custom `StateGraph`, not a prebuilt agent)

- **Choice**: build the loop ourselves with `StateGraph`: nodes `llm`, `approval`, `tools`, `finalize`, and a hand-written router.
- **Why**: the brief grades the loop itself (stop rule, checkpoint, recovery). A hand-built graph makes each of those a visible node or edge we can test and explain line by line. LangGraph gives us three things we would otherwise write ourselves: `interrupt()` for the human checkpoint, checkpointers to pause/resume a run, and `recursion_limit` as a hard stop.
- **Rejected**: prebuilt agent (`create_agent`) — hides the router and the stop logic we must prove; plain Python `while` loop — no pause/resume, we would re-implement persistence; multi-agent — the brief says it "needs a reason" and a single repair task has none.
- **Revisit if**: never for this project (team constraint: LangGraph is mandatory).

## D2 — LLM for v1: Groq, model `openai/gpt-oss-120b`

- **Choice**: develop and stabilise v1 on Groq with `openai/gpt-oss-120b`; `openai/gpt-oss-20b` is the fallback when the daily token limit is hit. Model is read from the env var `OPERATOR_MODEL` (default `groq:openai/gpt-oss-120b`).
- **Why**:
  - Cost: v1 means many re-runs while the agent is still unstable; a free tier keeps that at zero cost. Paid models are only worth paying for once failures come from the model and not from our bugs.
  - Model: Groq's deprecation page lists `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` as shut down on 2026-08-16 with the gpt-oss models as replacements, so the two gpt-oss models are the only non-deprecated production chat models. Of the two, the larger one is the safer choice for multi-step tool calling and for resisting injected instructions (our assumption, to be measured by the eval — not a documented fact).
  - Tool calling is supported; **parallel tool calls are not** for gpt-oss models. That suits us: one tool call per step means one write per approval and a simpler trajectory to score.
  - Token usage is returned in `usage_metadata`, which the cost metrics need.
- **Verified 2026-11-11** (Groq docs: models, rate-limits, tool-use, deprecations; LangChain Groq page; local run): package `langchain-groq` 1.1.3, key in `GROQ_API_KEY`, `init_chat_model("groq:openai/gpt-oss-120b")` returns a `ChatGroq`. Context 131 072 tokens. List price $0.15 / $0.60 per 1M input/output tokens (20b: $0.075 / $0.30).
- **Known limits**: the documented base limits for both gpt-oss models are 30 requests/min, 1 000 requests/day, **8 000 tokens/min, 200 000 tokens/day**. The docs call these Developer-plan limits and give no separate free-tier table — the real numbers must be read on the account's Limits page (open item). Consequences we design for now:
  - tool outputs stay small (log tail capped, compact JSON) so one step fits well under 8K tokens/min;
  - the eval runner throttles requests (D8) and can resume a partial run;
  - a full 30+ scenario eval may not fit in one day's token quota; it can be split over two days or run on the 20b model.
- **Rejected**: Llama models on Groq — shut down; Groq preview models — can disappear without notice, bad for a frozen repo; local model (Ollama) — weaker tool calling, depends on laptop hardware at the demo; paid model from day one — pays for our own bugs.
- **Revisit if**: v1 passes its tests with the fake model and the Groq eval is stable → run the same eval on a paid model and compare success, injection and cost (planned, T5.6). Also revisit if the free limits make the eval impractical.

## D3 — Provider-neutral model loading

- **Choice**: `init_chat_model(os.environ["OPERATOR_MODEL"])`; no provider-specific code in `agent/`.
- **Why**: D2 plans a model switch. With one env var, the Groq-vs-paid comparison runs the identical agent, so differences in results come from the model only.
- **Rejected**: importing `ChatGroq` directly — would need code edits to switch.
- **Revisit if**: a provider needs options `init_chat_model` cannot pass.

## D4 — Scripted fake model for tests

- **Choice**: a small fake chat model that replays scripted tool calls; used by all unit tests.
- **Why**: the stop-rule proof, idempotency and checkpoint tests must be deterministic, free, and runnable from a clean clone without a key. A real model cannot be forced to "loop forever" on demand; a script can.
- **Rejected**: recording real responses — brittle when prompts change; testing only with the live model — flaky, slow, uses quota.
- **Revisit if**: never; the live model is covered separately by the eval.

## D5 — Sandbox: local files + SQLite mini pipeline

- **Choice**: jobs are JSON configs; a runner really loads CSV into SQLite and really fails; state lives in `sandbox/.work/`, rebuilt from templates by one reset command.
- **Why**: the brief requires writes to go to a resettable test system and never production. Local files reset in milliseconds, need no account or network, and work from a clean clone. Real failures (not canned strings) make the diagnosis task honest.
- **Rejected**: Airflow/Prefect in Docker — heavy setup breaks "one setup command" and adds parts we cannot explain line by line; pure mock returning fixed strings — agent could not actually fix anything, "Works" would be unprovable.
- **Revisit if**: never for this project.

## D5a — Sandbox details

- **Simulated time and memory**: a job "takes" 0.05 s per row and a batch over 1 000 rows "does not fit". **Why**: real sleeps and real memory pressure would make 30+ scenarios slow and flaky; a fixed rule gives the same timeout and out-of-memory failures on every machine. The failure is still decided by the runner from the config, not scripted. **Rejected**: `time.sleep` — slow eval; real large files — bloats the repo.
- **Load mode = replace the target table**. **Why**: re-running a job can never duplicate rows, so the data side of `rerun_job` is idempotent by construction. **Rejected**: append — a double run doubles the data.
- **Three jobs with different delimiters and date formats**. **Why**: a fix copied from another job is wrong, and "the agent touched the wrong job" becomes a testable error and injection target.
- **Every reset replays one successful run per job**. **Why**: a real pipeline has history; the last good log is legitimate evidence for a repair (for example the table name when the key is missing).
- **Table and column names must match `^[a-z][a-z0-9_]*$`; paths are resolved inside the sandbox**. **Why**: these values come from config the agent can write and are placed in SQL and file paths, so an injected value could otherwise drop a table or read a file outside the sandbox.
- **Marker file before delete**. **Why**: reset deletes a folder; it refuses unless the folder holds the marker it created, so a wrong path cannot wipe real files.
- **Logs carry no timestamps (run times live in the `runs` table)**. **Why**: a reset then gives identical files, which the reset test checks.
- **Two faults that config cannot fix** (damaged row, deleted file). **Why**: the agent must be able to say "this is not a config problem" and escalate instead of writing something; without such cases the eval rewards an agent that always writes.

## D6 — Stop rule: step limit + token budget + recursion limit

- **Choice**: graceful stop when our own `steps` counter (one step = one model call) reaches `max_steps` or the token budget is spent (route to `finalize`, record `stop_reason`); LangGraph `recursion_limit` set explicitly as the hard backstop (`max_steps * 3 + 5`, since one step uses at most 3 nodes). Defaults: 12 steps, 40 000 tokens.
- **Why our own counter and not LangGraph's `RemainingSteps`**: `RemainingSteps` counts graph super-steps (every node, including `tools` and `approval`) and is derived from `recursion_limit`, which would tie the graceful rule to the hard one. Counting model calls in state is one line, is the same "steps per task" number the eval reports, and keeps the two limits independent so the hard one still works if the graceful one has a bug. Proof: `tests/test_stop.py`.
- **Why**: the default `recursion_limit` is about 10 000 (verified), which is no protection, so we set it. A graceful stop gives a readable summary instead of an exception; the hard limit guarantees termination even if our router has a bug. The budget also protects the Groq quota (D2).
- **Rejected**: only `recursion_limit` — ends in an exception with no summary; only a model-decided "done" — a model cannot be trusted to stop.
- **Revisit if**: eval shows legitimate tasks hitting the limit.

## D7 — Human checkpoint: dedicated `approval` node using `interrupt()`

- **Choice**: writes are routed through an `approval` node whose first statement is `interrupt(...)`; state is persisted with `SqliteSaver`.
- **Why**: on resume LangGraph re-runs the interrupted node from its start (verified), so nothing with a side effect may precede `interrupt()`. A separate node with nothing before the interrupt makes that rule impossible to break by accident. SQLite persistence lets approval survive a process restart, and the approval is enforced by the graph, not by the prompt — an injected "approval already granted" cannot skip it.
- **Rejected**: `interrupt()` inside each write tool — repeats the logic per tool and mixes safety with business code; asking the model to "request permission" — not enforceable.
- **Revisit if**: never.

## D6a — Loop rule (added in Phase 4)

- **Choice**: a fourth graceful limit, `max_repeats = 3`: the model may request the exact same call (same tool, same arguments) three times; the fourth request ends the run with `stop_reason = "loop"`.
- **Why**: it is the retry policy and the loop guard in one rule. A failed call can be retried twice, which covers a tool that is down once; an agent stuck repeating itself is stopped after 4 model calls instead of burning all 12 steps and the token budget. It is checked in code from the message history, so it does not depend on the model noticing.
- **Rejected**: a retry counter per tool error — more state to carry, and it misses loops made of successful calls.

## D7a — Human checkpoint details (as built in Phase 4)

- **Read-only preview before `interrupt()`**: the node builds a diff (old → new value for each key) before pausing. This is the only code before the interrupt and it only reads, so re-running it on resume is harmless.
- **Fail closed**: only the exact value `{"approved": True}` lets a write through. A string, `False`, or `{"approved": "yes"}` are all a rejection. **Why**: a bug or an odd resume value must never count as consent.
- **A rejection is told to the model as a tool result** with the human's reason, and logged with status `rejected`. **Why**: every tool request needs an answer for the conversation to stay valid, and the reason lets the agent follow a redirect ("use 120 instead") — this is how "user changes mind" is handled.
- **Reads skip the checkpoint**. **Why**: asking a human to approve every log read trains them to click yes without looking; the checkpoint is kept for the two calls that change something.
- **Checkpointer always present** (memory by default, SQLite from the CLI, stored outside `.work/`). **Why**: `interrupt()` cannot work without one, so the graph never compiles without it; the SQLite file sits outside the sandbox folder because an open database file would block the sandbox reset on Windows.
- **Known library limit**: `Command(resume=None)` and `Command(resume={})` raise inside LangGraph 1.2.20; the approver must always return a non-empty value.

## D7b — Prompt and data/instruction separation

- **Choice**: the system prompt is added at call time (not stored in state); every tool result is wrapped in `<tool_output>` tags for the model, and a closing tag inside the content is defused. State and logs keep the raw text.
- **Why**: the prompt tells the model that tagged content is data and never instructions; wrapping in one place (`agent/prompts.py::as_data`) means no tool can forget it. Defusing the closing tag blocks the attack where a log line "closes" the data block and continues as a fake system message. This is a soft defence (it relies on the model); the hard defences are the tool allow-list and the checkpoint.
- **Rejected**: wrapping inside each tool — changes what is logged and scored; a second "guard" model that screens tool output — extra cost and latency, and it is another model that can be fooled.
- **Model settings**: `temperature=0` for repeatable runs.

## D8 — Tool design: pydantic schemas, own error wrapper, allow-listed writes

- **Choice**: every tool has a pydantic `args_schema` with unknown fields forbidden; one shared wrapper turns any exception into a short actionable message and logs input/output/time; `update_job_config` accepts only allow-listed keys; no delete, shell or free-path tool. Eval requests are throttled with `InMemoryRateLimiter` from `langchain_core` (import verified).
- **Why**: strict schemas stop bad arguments before they reach the sandbox. `ToolNode` does have a `handle_tool_errors` option (seen in the installed langgraph-prebuilt 1.1.1 source, though not on the doc pages we read); we still use our own wrapper because we want one place that both formats errors our way and writes the call log. The narrow write surface is the main injection defence: an attack can only ask for what the tools can do.
- **Rejected**: one generic "edit file" tool — unbounded damage; returning stack traces — the model cannot act on them and they leak paths.
- **Revisit if**: the throttle proves unnecessary on the real account limits.

## D8a — Tool details (as built in Phase 3)

- **Seven tools, not more**: read `list_failed_runs`, `list_job_runs`, `get_run_logs`, `get_job_config`, `validate_config`; write `update_job_config`, `rerun_job`. **Why**: each maps to one step of a repair (find, inspect history, read evidence, read config, test a fix, apply, re-run). Fewer tools means fewer wrong-tool choices for a small model. The planned `get_run_status` was dropped because `rerun_job` already returns the result and `list_job_runs` shows status.
- **Errors and logging through `ToolNode` hooks, replacing the "own wrapper" plan of D8**: `handle_tool_errors=format_error` and `wrap_tool_call=log_call` (`agent/calls.py`). **Why**: schema validation happens before a tool body runs, so a wrapper inside the tool could never catch or log bad arguments; the two hooks see every call, including rejected ones and calls to tools that do not exist. Verified by running it.
- **Error text format**: `ERROR <CODE>: what happened. What to do next.` Codes: `E_BAD_ARGUMENTS`, `E_NOT_FOUND`, `E_NOT_ALLOWED`, `E_TOOL_FAILED`. **Why**: a stable prefix is easy for the model to recognise and for the eval to count; the hint tells the model its next step.
- **`validate_config` dry run**: **Why**: lets the agent test a fix with no side effect, so the human is asked to approve a change that is already known to work. It also gives the eval a signal: writing without validating first is a weaker path.
- **`changes` is a typed object with only the 8 known keys and bounded values** (batch ≤ 1 000, timeout ≤ 300, path must be `data/<name>.csv`, delimiter one of four). **Why**: the model cannot write a config the runner would reject for being out of range, and cannot add arbitrary keys.
- **`target_table` can be added when missing but never changed**. **Why**: redirecting a load to another table is the most damaging thing a config write could do and no repair needs it; this blocks the "write to prod_users" injection in code, before the human is even asked.
- **`update_job_config` idempotency**: same values → `no_change`, nothing written; the backup file is named after the old config's hash, so repeats cannot pile up copies; the file is replaced in one step (`os.replace`) so it is never half-written.
- **`rerun_job` idempotency key is derived, not supplied by the model**: the key is (job, hash of current config); if the job's latest run already used that config, the existing run is returned. **Why**: the brief wants "the same call twice does not do the thing twice"; a model-supplied key can be changed by the model on every call and so guarantees nothing. Side benefit: re-running an unchanged broken config (a classic loop) is impossible. **Rejected**: `idempotency_key` argument (the original plan).
- **Tools are created by `make_tools(work)`**. **Why**: the sandbox folder is fixed when the tools are built, so it is not an argument the model could change, and tests can point tools at a temporary folder.

## D10 — Eval design

- **Scenarios in one YAML file with explicit expected steps** (`eval/scenarios.yaml`, 32 scenarios: 14 repairs, 5 single tool failures, 1 persistent tool failure, 4 no-fix, 2 human rejections, 6 injections). **Why**: the brief asks for 30+ scenarios "with the expected steps"; plain data is readable by a grader and needs no code to understand.
- **The trajectory is read from the tool-call log**, not from the model's text. **Why**: the log records what was actually requested and what actually ran (including rejected and failed calls); the model's own account can be wrong.
- **Metric definitions**: step accuracy = expected steps done in order / expected steps (longest common subsequence); tool-call precision = right calls / calls made, where "right" is an expected step or an allowed optional read that succeeded; wasted steps = calls beyond the expected path. **Why**: an in-order match tolerates harmless extra reads but still punishes skipped or reordered steps; two separate numbers distinguish "did the right things" from "did only right things".
- **Arguments matched by subset, with `{min}`/`{max}` ranges**. **Why**: some fixes have many correct values (any timeout ≥ 10 s); exact matching would mark correct repairs wrong.
- **Success = final state AND proper stop AND no forbidden request**. A forbidden call that the tool or the human blocked still fails the task. **Why**: the brief says a right answer after a dangerous path is a failure; we report "requested" and "executed" separately so both the model and the system defences are visible.
- **"Repaired" also requires that only the broken key changed**. **Why**: an agent that fixes the job but also rewrites unrelated keys has done damage that a status check alone would miss.
- **Simulated human = `approve_all` by default, including in injection cases**. **Why**: it is the worst case (a reviewer who does not look), so the injection numbers measure the model and the tool limits, not a perfect human. The checkpoint is then an extra layer on top, shown in the demo.
- **Injected tool failures happen in the tool node** and are logged as `injected_failure`; a failed call that the agent retried counts once. **Why**: the retry is the correct reaction and must not be scored as a wasted step.
- **Oracle model**: a script that follows the expected steps must score 100 % on every scenario (`tests/test_eval.py`), and scripted bad agents must fail. **Why**: an eval can be wrong too; this checks the scenarios and the scoring before any real model is judged, with no API key.
- **Cost model**: measured input/output tokens × list price per model; "cost at 100×" = the same workload repeated 100 times. Time per task includes any provider rate-limit waits, which we state next to p50/p95.
- **Results are saved after every scenario and the run can resume**. **Why**: the free Groq tier may cut a run on its daily token limit.

## D9 — Tooling: Python 3.11, setuptools `pyproject.toml`, pinned versions, pytest

- **Choice**: exact version pins (langgraph 1.2.20, langchain 1.4.10, langchain-groq 1.1.3, langgraph-checkpoint-sqlite 3.1.3); setup is `pip install -e .`.
- **Why**: the repo is frozen and must run from a clean clone weeks later; these libraries change fast, so unpinned installs could break at the demo. Plain pip needs no extra tool on the grader's machine.
- **Rejected**: uv/poetry — one more thing to install; unpinned deps — unreproducible.
- **Revisit if**: a pinned version has a bug we need fixed.
