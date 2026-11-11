# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 2 — Sandbox (not started) |
| Last finished task | T1.4 (Phase 1 complete) |
| Next task | T2.1 (runner) → T2.2 (faults) → T2.3 (seed/reset) → T2.4 |
| Repo | https://github.com/alaabousselmi/The-Operator (branch `main`) |
| Code written | `agent/state.py`, `agent/stop.py`, `agent/graph.py` (llm/tools/finalize, no approval yet), `eval/fake_model.py`, `tests/test_stop.py` |
| Tests passing | 8/8 (`.venv/Scripts/python -m pytest -q`) |

## Blocked / needs the user

1. **T0.5 (user)**: Groq API key in `.env` + real free-tier limits from the Groq console. Not blocking until T5.5.

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

## Problems met (feeds postmortem.md)

- Planned to use LangGraph `RemainingSteps` for the graceful stop; on reading its source it counts super-steps and depends on `recursion_limit`, so we switched to our own model-call counter (D6).
- The doc pages did not show `ToolNode(handle_tool_errors=...)` but the installed source has it: docs summaries are not enough, check the installed code.

