# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 3 — Tools (not started) |
| Last finished task | T2.4 (Phases 1-2 complete) |
| Next task | T3.1 (read tools) → T3.2, T3.3 (write tools) → T3.5 (tests) |
| Repo | https://github.com/alaabousselmi/The-Operator (branch `main`) |
| Code written | Phase 1: `agent/{state,stop,graph}.py`, `eval/fake_model.py`. Phase 2: `sandbox/{paths,runner,faults,reset,seed,make_templates}.py` + `templates/` |
| Tests passing | 40/40 (`.venv/Scripts/python -m pytest -q`) |

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
- 2026-11-11 — Phase 2 done: sandbox runner, 9 faults, seed/reset; 40 tests pass.

## Sandbox facts for Phase 3

- All sandbox functions take `work: Path` (default `sandbox/.work`); tests pass `tmp_path / "work"`. Tools must do the same.
- Config keys: `source_path, delimiter, columns, date_column, date_format, batch_size, timeout_seconds, target_table`. Limits: batch ≤ 1000 rows, 0.05 s/row vs `timeout_seconds`, 200 rows per file.
- Error codes: `E_SOURCE_NOT_FOUND, E_COLUMN_MISSING, E_DATE_FORMAT, E_OUT_OF_MEMORY, E_TIMEOUT, E_CONFIG_KEY_MISSING, E_CONFIG_INVALID, E_BAD_ROW, E_PATH_OUTSIDE_SANDBOX`.
- After a reset runs are `run_0001..0003` (success); a seeded failure is `run_0004`.
- Windows: always close SQLite connections (`contextlib.closing`) or reset cannot delete the db.

## Problems met (feeds postmortem.md)

- Planned to use LangGraph `RemainingSteps` for the graceful stop; on reading its source it counts super-steps and depends on `recursion_limit`, so we switched to our own model-call counter (D6).
- The doc pages did not show `ToolNode(handle_tool_errors=...)` but the installed source has it: docs summaries are not enough, check the installed code.
- Multi-file bash heredocs failed on Windows Git Bash (quote parsing); files are now written one by one.
- Sandbox snapshot test first counted SQLite's automatic index as a table; filter `sqlite_master` on `type = 'table'`.

