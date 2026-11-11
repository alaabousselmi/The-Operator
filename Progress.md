# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 0 — Setup |
| Last finished task | T0.1 |
| Next task | T0.2 (GitHub repo) → T0.3 (pick LLM) → T0.4 → T1.1 |
| Code written | none yet |
| Tests passing | n/a |

## Blocked / needs the user

1. **GitHub repo (T0.2)**: `gh` CLI is not installed, so the repo could not be created from here. Local git repo exists with the first commit. Either install `gh` (`winget install GitHub.cli`, then `gh auth login`) or create an empty repo on github.com and give the URL; then `git remote add origin <url>; git push -u origin main`.
2. **LLM provider/model (T0.3)**: not chosen. Needs an API key in `.env` before T5.5 only.
3. **Instructor approval** of the topic by end of Week 11 (T0.4).
4. **Team members** for the README Contributions section.

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

## Problems met (feeds postmortem.md)

- (none yet — add every real problem here as it happens)
