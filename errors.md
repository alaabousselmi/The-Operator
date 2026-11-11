# Error taxonomy

What can go wrong while the agent repairs a pipeline job, what the system does about it, and the test that shows it. Run all of them with `pytest tests/test_errors.py`.

Two kinds of evidence are given for each class:

- **Test**: a deterministic test with a scripted model. It proves what the *system* does (the message the model receives, what changes in the sandbox, how the run ends), whatever the model decides.
- **Eval scenario**: a scenario in `eval/scenarios.yaml` run with the real model. It measures whether the *model* then reacts correctly. Results are in `eval/results/`.

## The classes

| # | Class | Example | What the agent/system does | Test (`tests/test_errors.py`) | Eval scenario |
|---|---|---|---|---|---|
| 1 | **Tool down** (once) | `get_run_logs` does not respond | The model receives `ERROR E_TOOL_UNAVAILABLE: ... Retry the same call once.` and retries. The same call may be made 3 times in total. | `test_tool_down_once_the_retry_succeeds` | `toolfail_logs_unavailable_once`, `toolfail_list_unavailable_once`, `toolfail_rerun_unavailable_once` |
| 2 | **Tool down** (for good) | `update_job_config` never responds | After 3 identical attempts the loop rule ends the run (`stop_reason = loop`). Nothing was written. The final note says so. | `test_tool_down_for_good_the_run_stops_without_writing` | `toolfail_update_always_down` |
| 3 | **Bad arguments** | `batch_size: 50000`, unknown key, malformed id | The schema rejects the call before the tool runs. The model receives `ERROR E_BAD_ARGUMENTS: <field>: <problem>. Fix the arguments and call the tool again.` Nothing changes. | `test_bad_arguments_are_refused_with_a_message_the_model_can_fix` (+ 13 cases in `tests/test_tools.py`) | seen in the real run: one bad call to `list_job_runs`, corrected on the next step |
| 4 | **Empty result** | Nothing is failing; or a tool answers with nothing | A genuinely empty result is stated in words (`No job is currently failing. Nothing to repair.`) so the model does not mistake it for an error. An empty answer from a failing tool can be retried. | `test_empty_result_is_stated_in_words`, `test_empty_result_from_a_failing_tool_can_be_retried` | `nofix_nothing_is_failing`, `toolfail_logs_empty_once` |
| 5 | **Wrong tool** | A tool that does not exist; a write aimed at a healthy job | Unknown tool: the model receives the list of valid tools. Write on a job that is not failing: refused with `E_NOT_ALLOWED` (a job that passes cannot be changed). The human also sees the job name in the approval request. | `test_wrong_tool_a_tool_that_does_not_exist`, `test_wrong_tool_a_write_on_a_healthy_job_is_refused` | all `repair_*` scenarios check that no other job changed |
| 6 | **Loop** | The model repeats the same call | The 4th identical request (same tool, same arguments) ends the run with `stop_reason = loop`. Independent backstops: 12 steps, 40 000 tokens, LangGraph recursion limit. | `test_loop_the_same_call_again_and_again_is_stopped` (+ `tests/test_stop.py`, the stop-rule proof) | "stop rule exceeded" count in every eval run |
| 7 | **Timeout** | A tool gives no answer in time; or the job itself exceeds `timeout_seconds` | Tool timeout: `ERROR E_TOOL_TIMEOUT ... Retry the same call once.`, same handling as class 1. Job timeout: it is an ordinary fault (`E_TIMEOUT` in the run log) that the agent repairs by raising `timeout_seconds`. | `test_tool_timeout_once_the_retry_succeeds`, `test_job_timeout_is_a_fault_the_agent_can_repair` | `toolfail_validate_timeout_once`, `repair_timeout_too_low_*` |
| 8 | **User changes mind** | The human rejects a write, with or without a new instruction | The write is not executed. The model receives `REJECTED by the human reviewer. Reason: ...` as the tool result, and the rejection is logged. The agent follows the reason if it asks for something else, otherwise it stops and reports. | `test_user_changes_mind_the_rejection_reaches_the_model_and_nothing_is_written` (+ `tests/test_checkpoint.py`) | `human_rejects_the_repair`, `human_rejects_then_asks_for_another_value` |
| 9 | **Partial failure** | Step 3 of 5: config updated, then the re-run cannot be started; or a limit stops the run mid-repair | The run ends cleanly and the final note lists the writes already done. The old config is in `backups/`. Because both writes are idempotent, running the agent again finishes the job: the update answers `no_change` and only the re-run happens. | `test_partial_failure_step_3_of_5_fails_and_a_second_run_finishes_the_job`, `test_stopped_by_a_limit_mid_repair_reports_the_writes_done` | `toolfail_rerun_unavailable_once` |
| 10 | **Unfixable fault** | Damaged data line, deleted source file | No config change can make the job pass, so `update_job_config` refuses every change (`E_NOT_ALLOWED: The job would still fail`), and `rerun_job` starts no new run for an unchanged config. The agent is told to change nothing and escalate to a human. | `test_unfixable_fault_no_config_write_is_accepted` | `nofix_corrupt_source_*`, `nofix_source_deleted_customers` |
| 11 | **Over-fixing** | The repair plus changes nobody needs (what an injected "known fix" asks for) | `update_job_config` accepts only a minimal repair: every changed key must be necessary for the job to pass. Extra keys are refused by name. | `test_over_fixing_extra_keys_are_refused` | `inject_log_plausible_operator_note` |

## How errors reach the model

Every failure comes back as one line of text in the same shape, never a stack trace:

```
ERROR <CODE>: <what happened>. <what to do next>.
```

| Code | Meaning | Expected reaction |
|---|---|---|
| `E_BAD_ARGUMENTS` | The schema rejected the arguments | Fix the named field and call again |
| `E_NOT_FOUND` | Unknown job or run id (the message lists valid ones) | Use a valid id |
| `E_NOT_ALLOWED` | The write is not a minimal repair of a failing job | Do not insist; send only the needed keys, or stop |
| `E_TOOL_UNAVAILABLE`, `E_TOOL_TIMEOUT` | The tool did not answer | Retry once |
| `E_TOOL_FAILED` | Unexpected failure inside a tool | Retry once, then stop and report |
| `REJECTED by the human reviewer` | The human said no | Follow the reason, or stop and report |

Job failures (`E_DATE_FORMAT`, `E_COLUMN_MISSING`, `E_SOURCE_NOT_FOUND`, `E_OUT_OF_MEMORY`, `E_TIMEOUT`, `E_CONFIG_KEY_MISSING`, `E_BAD_ROW`) are not tool errors: they are the content of the run log that the agent has to diagnose.

## Recovery after failure

"When a tool fails once, how often does the agent still finish the task?" is measured on the five `tool_failure` scenarios (one injected failure each: unavailable ×3, timeout ×1, empty ×1).

| Run | Model | Recovered |
|---|---|---|
| 2026-11-11 (v1) | Groq `openai/gpt-oss-120b` | 5 / 5 |
| 2026-11-11 (v2, after the minimal-repair rule) | Groq `openai/gpt-oss-120b` | 5 / 5 |

Five scenarios, one run each: this shows the mechanism works, not a precise rate. Later runs are added to this table.

## What is not handled

- **The model provider itself failing** (rate limit, outage). The client retries a few times; after that the run raises and stops. A paused run can be resumed from its SQLite checkpoint, but there is no automatic resume.
- **Automatic rollback.** After a partial failure the old config is kept in `backups/`, but restoring it is a manual step: a rollback tool would be one more write the agent could be tricked into using.
- **Two jobs failing at once.** The tools support it, but no scenario tests it yet.
