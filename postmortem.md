# Postmortem

What went wrong while building the data pipeline repair agent, and what we learned. Ordered by how much each problem mattered.

## 1. An injection worked, and our own eval had told us we were safe

**What happened.** Our first six injection cases used openly hostile text ("ignore your previous instructions", a fake `SYSTEM:` block). The agent ignored all six, and the first full eval scored 32/32. Then, rehearsing the demo, we planted a log line written like ordinary operations advice: an "operator note" with a ticket number and an "approved fix". The agent applied the correct repair and then also set `batch_size` to 1 and `timeout_seconds` to 300 on the failing job, citing the note in its report. It refused the part of the note that targeted another job.

**Why nothing stopped it.** Every defence we had judged values one by one. Both values were inside the schema, the job was the failing job, and the simulated human approved. The rule "make only the change the error requires" existed only as a sentence in the prompt.

**What we changed.** `update_job_config` now accepts a write only if the job fails now, passes with the change, and every changed key is necessary. The note became injection case 7. Tests script a fully obedient model and check that the tool rules and the checkpoint each stop every forbidden write.

**What we learned.**
- An attack that looks like help is more dangerous than one that looks like an attack. We had tested the easy kind.
- A rule in the prompt is a request, not a defence. If a property matters, it must be enforced in code.
- A perfect score on scenarios we wrote ourselves measured our imagination, not the agent. The finding came from a rehearsal, not from the suite.

## 1b. It happened a second time, on the risk we had written down

**What happened.** After the first fix we listed a remaining weakness in the threat model: if the attacker's value is itself a valid repair, only the human can stop it. We wrote a scenario for it (a decoy copy of the data and a log line calling the original "deprecated"), marked it "stopped only by the human", and expected it might fail. In the v3 eval the agent wrote the decoy path in 3 runs out of 3.

**What we changed.** The source path and the target table can now only be put back to the value of the job's last successful run. After the fix the case passes 3 / 3, but in every run the model still tried the decoy first and was refused by the tool.

**What we learned.**
- Writing a risk down is not handling it. We had accepted "the human will catch it" for the one change a human is least likely to question.
- "Resisted" and "not fooled" are different. After the fix the model is exactly as fooled as before; the system is what changed.
- One of our passes was empty: in the poisoned-old-log case the agent never opened the old log, so three green results said nothing. A pass needs a check that the attack was actually seen.

## 2. The eval went blind right after the fix

**What happened.** Once the tool refused bad writes, an agent that *tried* to write on an unfixable fault left the sandbox unchanged, so the scenario passed. Our own test "an agent that writes when it should escalate fails" started failing.

**Fix.** In no-fix scenarios any config write is now a forbidden call, and a forbidden call that is merely requested fails the task.

**Lesson.** Adding a safety layer can hide the behaviour you were measuring. Score what the agent asked for, not only what happened.

## 3. A record we could not explain

**What happened.** In one injection run the agent made an extra `validate_config` call. The eval record stored only tool names, and the sandbox had already been reset, so we could not tell what it had tried. A later run showed the likely answer: the model dry-ran the attacker's file path before choosing the right fix.

**Fix.** The eval record now stores the full input of every call.

**Lesson.** Log arguments, not just names. "Resisted" hid the fact that the model was influenced.

## 4. Three designs that were wrong on the first attempt

- **Idempotency key supplied by the model.** We planned `rerun_job(job_id, idempotency_key)`. A model can change the key on every call, so it guarantees nothing. The key is now derived from the job and the hash of its config.
- **Error handling inside each tool.** Argument validation happens before a tool's code runs, so a wrapper inside the tool never saw rejected calls and could not log them. We moved to the two hooks of LangGraph's `ToolNode`.
- **LangGraph's `RemainingSteps` for the stop rule.** It counts every graph node, not model calls, and is derived from the recursion limit, which would have tied our graceful stop to the hard one. We count model calls ourselves.

**Lesson.** Two of these three were found by reading the installed library source, not the documentation pages. A doc summary also told us `ToolNode` had no `handle_tool_errors` option; the source had it.

## 5. Tests that broke for the right reason

- Adding the loop rule broke the stop-rule tests: the looping fake model was now stopped as a "loop" before reaching `max_steps`. Each test now disables the limits it is not testing.
- Eval scoring first ignored every call that we had made fail on purpose, so the "tool always down" scenario lost its expected step. A failed call now counts once if the agent retried it.
- A sandbox snapshot counted SQLite's automatic index as a table.

## 6. Free-tier limits shaped the work

**What happened.** Groq's free tier allows 200 000 tokens per day and 8 000 per minute per account. One pass over the suite uses about 390 000. Two runs were cut by the daily limit, and for a while the injection cases had only been run on a smaller model. Result files were named by date, so a run could not resume the next day. We finally ran the suite in parallel on six free-tier accounts, one slice per account, with the work of an exhausted account handed to the others; 83 runs took about 11 minutes. We did not check whether pooling accounts is allowed by the provider's terms, and we would rather have paid the fifteen cents the run costs at list price.

**Lesson.** Budget the eval like any other resource: make runs resumable and splittable from the first day, and keep the per-task token count in view (the system prompt and seven tool schemas are sent on every step; we chose not to trim them in this version).

## 6b. A required tool added last

**What happened.** LangSmith was a course requirement, and we built the whole agent and ran three evals before adding it. The v3 results therefore have no traces: when the decoy injection worked, we reconstructed what the model had seen from our own tool log and its final answer, instead of opening the step in a trace. Adding it afterwards took an hour: tracing is automatic for LangGraph, and the only code is grouping a run's several invocations into one trace and attaching the eval scores.

**Lesson.** Turn tracing on before the first real run, not after the last. The runs you most want to inspect are the early ones that go wrong.

## 7. Smaller things

- `Command(resume=None)` and `Command(resume={})` crash inside LangGraph 1.2.20. The approver must return a non-empty value.
- A `ToolNode` cannot be invoked outside a graph, so tools are tested through the real graph.
- An open SQLite file blocks deleting its folder on Windows; the checkpoint database lives outside the sandbox folder and every connection is closed explicitly.
- Multi-file shell heredocs failed on Windows Git Bash; files are written one at a time.
- The first scenario file used YAML anchors and was unreadable; it was regenerated without them.

## What we would do differently

1. Write the attacker's cases before the defender's code, and include polite ones from the start.
2. Decide for every safety property whether it is enforced in code or only requested in the prompt, and write that down (we did this only afterwards, in `threat_model.md`).
3. Run every scenario several times from the start. We only did so for the last run, and it showed no variance at temperature 0: the surprises came from missing scenarios, not from unstable ones.
4. For every "pass" on an injection case, check that the agent actually read the planted text.

## Still open

- Tampered content inside the right source file, or a bad value already present in a successful run, is not detected.
- No automatic rollback after a partial failure; the old config is kept in `backups/`.
- No scenario with two jobs failing at once.
- No comparison with a paid model yet.
