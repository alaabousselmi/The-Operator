# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 0 — Setup |
| Last finished task | T0.2 |
| Next task | T0.3 (pick LLM, under discussion) → T0.4 → T1.1 |
| Repo | https://github.com/alaabousselmi/The-Operator (branch `main`) |
| Code written | none yet |
| Tests passing | n/a |

## Blocked / needs the user

1. **LLM provider/model (T0.3)**: under discussion with the user. Needs an API key in `.env` before T5.5 only; Phases 1-4 use the fake model.

## Team (README Contributions)

Alaaeddine Bousselmi · Mohamed Amine Zouaoui · Seifeddine Knani · Walid Fakhfakh. Topic approved by the instructor.

## Decisions (with reason)

- Sandbox is a local mini pipeline (CSV → SQLite, JSON job configs, log files) under `sandbox/.work/`: real failures, trivially resettable, no cloud account.
- Two write tools (`update_job_config`, `rerun_job`), both idempotent, both behind `interrupt()`. No delete/shell tool on purpose.
- Stop rule = max steps (`RemainingSteps`, graceful) + token budget + `recursion_limit` (hard). Built and tested before the agent (T1).
- Approval lives in its own graph node whose first statement is `interrupt()`, because the node re-runs from the top on resume.
- Tool errors are caught in our own wrapper, not via `ToolNode(handle_tool_errors=...)` (that parameter was not confirmed in current docs).
- Provider-neutral model loading (`init_chat_model`) + scripted fake model so tests run without a key.
- `project3-operator.pdf` is git-ignored (course material, not ours to publish).

## Environment

- Windows 11, PowerShell, Python 3.11.9, git 2.52. `gh` missing.
- LangGraph facts verified against docs on 2026-11-11 (langgraph 1.2.20): see `Tasks.md` §2. Re-check only if an import fails.

## Log

- 2026-11-11 — T0.1 done: brief read, LangGraph docs checked, `Tasks.md` / `Progress.md` written, local git repo initialised.
- 2026-11-11 — T0.2 done: pushed to GitHub. Topic approved by instructor.

## Problems met (feeds postmortem.md)

- (none yet — add every real problem here as it happens)
