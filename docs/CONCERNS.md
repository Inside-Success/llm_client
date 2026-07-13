# LLM Client Concern Register

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Open Concerns

| ID | Concern | Severity | Current mitigation | Next evidence/action |
|---|---|---:|---|---|
| LLM-PORT-001 | Infrastructure breadth can obscure portfolio value. | High | Applied observability case frames traces as decision evidence. | Publish one downstream trace with a clear before/after decision. |
| LLM-PORT-002 | Observability can be mistaken for analytic proof. | High | Validation register separates runtime, trace, decision, and analysis validity. | Tie claims to downstream project artifacts. |
| LLM-PORT-003 | Prompt-evaluation logic can drift back into this repo. | Medium | Capability decomposition assigns prompt-eval semantics to `prompt_eval`. | Keep new evaluation features behind explicit boundary decisions. |
| LLM-PORT-004 | Runtime substrate can bloat into workflow orchestration. | Medium | ADR 0010 keeps workflow orchestration above this layer. | Use separate workflow runtime when durable orchestration is required. |
| LLM-PORT-005 | Model/provider behavior changes over time. | Medium | Model registry, trace logging, and errors/cost queries expose drift. | Use empirical traces before changing task policy. |
| LLM-RUNTIME-006 | Structured callers could not require native JSON schema; provider schema rejection silently changed execution to Instructor, whose internal retries are separate from `RetryPolicy`. | High | Plan 99 implements an opt-in strict execution policy with sync/async rejection, trace, replay, and default-auto controls. | Bind the exact merged commit in downstream Plan 0141 and inspect its first live MiniMax-M3 trace. |
| LLM-VERIFY-007 | The mandatory `complete_plan.py` non-E2E pytest pass can wait indefinitely without naming the active test, so a stalled gate is not diagnostic. | Medium | Plan 99 uses focused behavioral/trace gates and records the interrupted broad-run evidence honestly. | Add per-test timeout/current-test reporting to the completion harness, then rerun Plan 99 completion without bypassing failures. |

## Portfolio Judgment

`llm_client` is valuable supporting evidence for governed AI engineering. It
should not lead the CIA/analyst-facing portfolio by itself, but it can make
applied systems more credible when a reviewer can see that model behavior,
costs, errors, and structured-output failures were visible and acted on.
