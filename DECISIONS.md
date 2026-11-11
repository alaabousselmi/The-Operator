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

## D6 — Stop rule: step limit + token budget + recursion limit

- **Choice**: graceful stop when `remaining_steps` is low or the token budget is spent (route to `finalize`, record `stop_reason`); LangGraph `recursion_limit` set explicitly as the hard backstop.
- **Why**: the default `recursion_limit` is about 10 000 (verified), which is no protection, so we set it. A graceful stop gives a readable summary instead of an exception; the hard limit guarantees termination even if our router has a bug. The budget also protects the Groq quota (D2).
- **Rejected**: only `recursion_limit` — ends in an exception with no summary; only a model-decided "done" — a model cannot be trusted to stop.
- **Revisit if**: eval shows legitimate tasks hitting the limit.

## D7 — Human checkpoint: dedicated `approval` node using `interrupt()`

- **Choice**: writes are routed through an `approval` node whose first statement is `interrupt(...)`; state is persisted with `SqliteSaver`.
- **Why**: on resume LangGraph re-runs the interrupted node from its start (verified), so nothing with a side effect may precede `interrupt()`. A separate node with nothing before the interrupt makes that rule impossible to break by accident. SQLite persistence lets approval survive a process restart, and the approval is enforced by the graph, not by the prompt — an injected "approval already granted" cannot skip it.
- **Rejected**: `interrupt()` inside each write tool — repeats the logic per tool and mixes safety with business code; asking the model to "request permission" — not enforceable.
- **Revisit if**: never.

## D8 — Tool design: pydantic schemas, own error wrapper, allow-listed writes

- **Choice**: every tool has a pydantic `args_schema` with unknown fields forbidden; one shared wrapper turns any exception into a short actionable message and logs input/output/time; `update_job_config` accepts only allow-listed keys; no delete, shell or free-path tool. Eval requests are throttled with `InMemoryRateLimiter` from `langchain_core` (import verified).
- **Why**: strict schemas stop bad arguments before they reach the sandbox. Our own wrapper is used because a `handle_tool_errors` option on `ToolNode` was not found in the current docs, and we want one place that both formats errors and writes the call log. The narrow write surface is the main injection defence: an attack can only ask for what the tools can do.
- **Rejected**: one generic "edit file" tool — unbounded damage; returning stack traces — the model cannot act on them and they leak paths.
- **Revisit if**: the throttle proves unnecessary on the real account limits.

## D9 — Tooling: Python 3.11, setuptools `pyproject.toml`, pinned versions, pytest

- **Choice**: exact version pins (langgraph 1.2.20, langchain 1.4.10, langchain-groq 1.1.3, langgraph-checkpoint-sqlite 3.1.3); setup is `pip install -e .`.
- **Why**: the repo is frozen and must run from a clean clone weeks later; these libraries change fast, so unpinned installs could break at the demo. Plain pip needs no extra tool on the grader's machine.
- **Rejected**: uv/poetry — one more thing to install; unpinned deps — unreproducible.
- **Revisit if**: a pinned version has a bug we need fixed.
