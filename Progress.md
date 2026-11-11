# Progress — Data Pipeline Repair Agent

Read this file first in a new session, then only the task you are on in `Tasks.md`. Do not re-read the PDF: everything needed from it is in `Tasks.md`.

## Status

| Field | Value |
|---|---|
| Last updated | 2026-11-11 |
| Current phase | 1 — Stop rule (not started) |
| Last finished task | T0.4 |
| Next task | T1.1 (state) → T1.2 → T1.3 → T1.4 (stop-rule proof) |
| Repo | https://github.com/alaabousselmi/The-Operator (branch `main`) |
| Code written | setup only: `pyproject.toml`, empty `agent/ sandbox/ eval/ tests/` packages |
| Tests passing | n/a |

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

## Problems met (feeds postmortem.md)

- (none yet — add every real problem here as it happens)
