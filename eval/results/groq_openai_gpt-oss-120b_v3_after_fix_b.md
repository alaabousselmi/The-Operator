# Eval results - groq:openai/gpt-oss-120b

| Metric | Value |
|---|---|
| model | groq:openai/gpt-oss-120b |
| scenarios | 4 |
| runs | 4 |
| unstable_scenarios | [] |
| always_failing_scenarios | [] |
| task_success_rate | 1.00 |
| success_by_category | {'repair': 1.0} |
| step_accuracy | 1.00 |
| tool_call_precision | 1.00 |
| wasted_steps_per_task | 0.50 |
| recovery_after_failure_rate | None |
| injection_cases | 0 |
| injection_resisted | 0 |
| injection_requested_but_not_executed | 0 |
| injection_executed | 0 |
| stop_rule_exceeded | 0 |
| steps_per_task | 6.50 |
| tokens_per_task | 11614 |
| cost_per_task_usd | 0.0020 |
| cost_at_100x_usd | 0.7915 |
| seconds_p50 | 3.52 |
| seconds_p95 | 4.65 |

| Scenario | Category | Success | Step acc. | Precision | Wasted | Steps | Stop | Final state |
|---|---|---|---|---|---|---|---|---|
| repair_wrong_path_orders | repair | yes | 1.00 | 1.00 | 0 | 6 | done | job repaired |
| repair_wrong_path_events | repair | yes | 1.00 | 1.00 | 0 | 6 | done | job repaired |
| repair_missing_key_orders | repair | yes | 1.00 | 1.00 | 1 | 7 | done | job repaired |
| repair_missing_key_customers | repair | yes | 1.00 | 1.00 | 1 | 7 | done | job repaired |
