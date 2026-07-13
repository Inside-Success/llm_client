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
| LLM-VERIFY-007 | The non-E2E suite appeared stalled because CLI smoke launches 15 cold Python imports, mocked client tests inherited real cross-process provider cooldowns, and the completion helper's fixed 300-second timeout was below normal suite duration. | Medium | Mocked clients now disable shared cooldown waiting; dedicated rate-limit/kernel tests retain coverage; the helper exposes a positive CLI timeout (900-second default) and captured-progress diagnostics with unit controls. | Rerun the mandatory Plan 99 completion helper and calibrate the default from observed CI duration if 900 seconds is insufficient. |
| LLM-VERIFY-008 | A June backup merge restored pre-Plan-32 tool-decorator production code while retaining the accepted sync/registry/type tests, leaving seven failures on `origin/main`. | High | Restored accepted Plans 32/47 sync support, `ToolRegistry.has`, and concrete annotation metadata while preserving later goal/complexity/result-type fields; 38 decorator/public-surface tests pass. | Keep the full completion suite green and prevent unverified backup merges from replacing newer implementation with older snapshots. |
| LLM-VERIFY-009 | The repository-wide `make check` lint gate is red on clean `origin/main` with 315 Ruff violations, so it cannot currently certify otherwise-green increments. | High | Plan 97 records the exact inherited baseline; its changed modules are Ruff-clean and 365 focused/wider regression tests pass. | Land a dedicated lint-baseline repair or scoped-baseline gate, then require `make check` on every merge; do not describe the current default branch as fully green. |

## Portfolio Judgment

`llm_client` is valuable supporting evidence for governed AI engineering. It
should not lead the CIA/analyst-facing portfolio by itself, but it can make
applied systems more credible when a reviewer can see that model behavior,
costs, errors, and structured-output failures were visible and acted on.
