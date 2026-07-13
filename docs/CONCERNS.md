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
| LLM-RUNTIME-006 | Structured callers could not require native JSON schema; provider schema rejection silently changed execution to Instructor, whose internal retries are separate from `RetryPolicy`. | High | Strict routing and exact replay are implemented. After two rejected repairs, fresh independent review accepted `5ed2a1e` with real four-path capture-to-replay and the full adversarial matrix. | Require Plan 0141 to pin the implementation and acceptance-evidence commits and pass its downstream replay before runtime authorization. |
| LLM-VERIFY-007 | The non-E2E suite appeared stalled, and the later completion record masked a separate declared-test integrity failure. | High | Timeout/cooldown diagnostics are implemented; AST node resolution and exact declarations now make `check_plan_tests.py --plan 99` execute 375 tests and exit zero locally. | Keep the command in independent acceptance and plan completion so registry drift cannot recur. |
| LLM-VERIFY-008 | A June backup merge restored pre-Plan-32 tool-decorator production code while retaining the accepted sync/registry/type tests, leaving seven failures on `origin/main`. | High | Restored accepted Plans 32/47 sync support, `ToolRegistry.has`, and concrete annotation metadata while preserving later goal/complexity/result-type fields; 38 decorator/public-surface tests pass. | Keep the full completion suite green and prevent unverified backup merges from replacing newer implementation with older snapshots. |
| LLM-VERIFY-009 | The first Plan 99 replay repair was called locally exact after policy-field tests, but independent review found that the surrounding snapshot envelope could shed or reinterpret that authority and still dispatch. | High | Added TDD attacks for all-version stored-fingerprint mismatch, full v2-to-v1 downgrade, missing/malformed support metadata, API/kind reinterpretation, unknown envelope/control fields, non-replayable message values, schema drift, and omitted text execution mode; genuine v1 remains a positive control. | For replay/versioned envelopes, test the full state-transition matrix (integrity, downgrade, metadata deletion, kind substitution, unknown fields, and every captured control) rather than only fields inside the new policy object. |
| LLM-VERIFY-010 | The second Plan 99 repair was called locally green after real public-path capture tests and builder-level replay tests, but no test fed each real captured snapshot into replay. The producer's timeout-disabled sentinel and lossy normalization therefore disagreed with the consumer while all focused tests passed. | High | Third repair uses capture-to-replay tests for all four public APIs and intrinsic unsupported-value markers for every non-JSON-native coercion; independent review accepted exact commit `5ed2a1e`. | Preserve producer-to-actual-consumer round trips as mandatory evidence for persisted contracts; field inspection and hand-built consumer fixtures remain supporting evidence only. |

## Portfolio Judgment

`llm_client` is valuable supporting evidence for governed AI engineering. It
should not lead the CIA/analyst-facing portfolio by itself, but it can make
applied systems more credible when a reviewer can see that model behavior,
costs, errors, and structured-output failures were visible and acted on.
