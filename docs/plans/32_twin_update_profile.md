# Plan #32: twin_update Profile

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #31 (TaskFamily abstraction)
**Blocks:** eval_audit profile (Plan #33); future system-improvement meta-duet

---

## Gap

**Current:** The duet chassis (Plans #29-31) ships with two profiles: `generic` (universal) and `plan_doc_review` (plan-doc-aware). Neither understands customer-twin work. The reviewer can't score against PCM v2's 5-layer personality model, Twin Fidelity's three signoff axes (B/B-prompt/C), or the proof-authority contract that every customer-facing closeout must honor. Routing twin work through the chassis today means jamming PCM/rubric findings into the generic `nits[]` and `unverified_claims[]` buckets — losing the structure that makes the rubric enforceable.

**Target:** A `twin_update` profile that:
- Adds `pcm_layer_findings` keyed to PCM v2's 5 layers (Knowledge / Voice / Reasoning / Values+Boundaries / Emotional).
- Adds `twin_fidelity_rubric_misses` keyed to the three axes from `twin_fidelity_signoff_rubric.md` (Axis B proof depth, Axis B-prompt sub-axis, Axis C claim breadth).
- Adds `proof_authority_gaps` enforcing the customer-twin proof contract from root `AGENTS.md` (every claim about current behavior must trace to personal reproduction; missing authority artifacts are blocking by default).
- Adds `scope_violations` against customer constraints carried in the task.
- Adds `signoff_axes_claim` to the implement review so the reviewer must declare which Axis B / B-prompt / C levels the change actually earned.

Profile registers from `llm_client.workflow.profiles.twin_update`. Lives library-owned for v1 to avoid a consumer-loader CLI diversion; can be promoted to workspace-owned later by adding `--profile-module` to the CLI when a second domain profile lands.

**Why:** Customer-twin work is the load-bearing use case the duet was built for. Without a twin-aware profile the chassis is a tool looking for a domain. With it, every twin update can run through a reviewer that scores against the actual rubric, surfaces PCM layer regressions, and refuses to call something `prod_verified` when the proof authority is incomplete — the same gates Brian's existing skills enforce manually.

---

## References Reviewed

- `workspace/docs/references/twin_fidelity_signoff_rubric.md:24-139` — Axis B (6 states), Axis B-prompt (5 states), Axis C (3 states), row statuses. These map directly to the `twin_fidelity_rubric_misses` schema.
- `workspace/docs/references/twin_fidelity_signoff_rubric.md:182-186` — the five hard-stop overclaim rules the profile's prompt addendum must surface verbatim so the reviewer knows when to call out overclaim.
- `reference/experimental_garbage/pcm-v1-working-set/vision/pcm_v2_full.md:1-122` — PCM v2's 5 layers (Knowledge / Voice / Reasoning / Values+Boundaries / Emotional) plus the per-layer signal-density model. Maps to the `PcmLayerFinding` Literal.
- Root `/home/brian/brian-work-next/AGENTS.md` Customer-twin proof and authority contract — every current-behavior claim must trace to personal reproduction; missing authority artifacts are blocking by default. Maps to `ProofAuthorityGap`.
- `llm_client/workflow/duet_base.py:62-89` — `TaskFamily` dataclass with `context_loader` callable, the extension hook for the customer/ai/ticket params this profile needs.
- `llm_client/workflow/duet.py:62-77` — `DuetTask` schema. Needs an `extra: dict[str, Any]` field so profiles can stash domain-specific per-task params without schema forks.
- `llm_client/workflow/profiles/plan_doc_review.py:32-79` — established pattern for a profile that specializes only `plan_review_schema` while reusing the generic `implement_review_schema`. twin_update specializes both.
- `tests/test_workflow_profiles.py` — established offline test pattern for profile schema validation.

---

## Files Affected

- `llm_client/workflow/duet.py` (modify) — `DuetTask.extra: dict[str, Any] = Field(default_factory=dict)`.
- `llm_client/workflow/profiles/twin_update.py` (create) — schemas + addenda + context_loader stub.
- `llm_client/workflow/profiles/__init__.py` (modify) — import `twin_update` so it auto-registers.
- `tests/test_workflow_profiles.py` (modify) — assertions for the twin_update profile shape, schema groundedness, and registry presence.
- `docs/plans/32_twin_update_profile.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append index row.

Out of scope (deliberately):
- A real customer dry-run. The profile ships with offline schema tests; the first live `duet-review --task-family twin_update` against a closed Maya CLI ticket is a separate slice that needs Brian to point at a specific ticket.
- A `--profile-module` CLI flag. Library-owned profile sidesteps the loader-plumbing problem for v1.
- Rich PCM v2 atom catalogue (per-layer signal-density tables, content-bucket weights). The Literal layer names are enough for a reviewer to score against; atom-level detail can land when the profile is proving out on real tickets.
- Live customer-prompt loader implementation. The `context_loader` is a stub that reads `task["extra"]` keys; the actual filesystem walk against a clone is a follow-up once the schema is validated.
- Auto-detection of which Axis B level a change has earned. The reviewer declares; chassis doesn't infer.
- `eval_audit` profile. Separate Plan #33 once twin_update is dry-run-validated.

---

## Plan

### Steps

1. Add `extra: dict[str, Any] = Field(default_factory=dict)` to `DuetTask` in `duet.py`. This is the small chassis change that lets profile context_loaders read per-task params (customer slug, ai slug, ticket id, etc.) without forking the task schema.
2. Define `PcmLayer` as a `Literal["Knowledge", "Voice", "Reasoning", "Values and Boundaries", "Emotional"]` plus a numeric mapping helper.
3. Define `AxisB`, `AxisBPrompt`, `AxisC` Literals from the rubric authority. Mirror the canonical short labels exactly (no longer-form renames; that's a separate decision per D2 ratification). `TwinFidelityRubricMiss.axis` also accepts `"row_status"` so reviewers can flag overclaim driven by row-status violations (e.g. critical row marked `partial` while claiming `qa_ready`), per `twin_fidelity_signoff_rubric.md:106-124`.
4. Define `PcmLayerFinding(layer, finding, severity, evidence_path)`, `TwinFidelityRubricMiss(axis, item, why_missed, suggested_remediation)`, `ProofAuthorityGap(claim, missing_artifact, why_blocking, narrower_claim_still_safe)`, `ScopeViolation(proposed_change, customer_constraint_violated, evidence_path)`. All `evidence_path` fields required (groundedness rule from Plan #30).
5. Define `TwinUpdatePlanReview(PlanReview)` with `pcm_layer_findings`, `twin_fidelity_rubric_misses`, `proof_authority_gaps`, `scope_violations`.
6. Define `PcmLayerRegression(layer, regression, severity, evidence_path)` and `SignoffAxesClaim(axis_b, axis_b_prompt, axis_c, overclaim_risk, reason)`. Define `TwinUpdateImplementReview(ImplementReview)` with `pcm_layer_regressions`, `signoff_axes_claim`, `published_prod_qa_evidence_path`.
7. Build `_PLAN_REVIEW_ADDENDUM` text that surfaces the 5 PCM layers (with one-line descriptions from PCM v2), the three rubric axes with their canonical level vocabulary, all five hard-stop overclaim rules from `twin_fidelity_signoff_rubric.md:182-186`, and the proof-authority contract requirement.
8. Build `_IMPLEMENT_REVIEW_ADDENDUM` text that requires the reviewer to declare `signoff_axes_claim` and to call out PCM layer regressions specifically (Voice fix that breaks Reasoning, etc.).
9. Build `_load_twin_context_pack(task)` context_loader that reads `task["extra"]` for `customer`, `ai`, `ticket_id`, `complaint_text`, `customer_constraints[]` and emits labeled blocks. Stub-only on filesystem walks for v1.
10. Wire registration in `profiles/__init__.py`.
11. Tests (`test_workflow_profiles.py`): registry has twin_update; schemas have the expected fields; groundedness enforced; addendum text mentions PCM layers and Twin Fidelity rubric axes; context_loader returns expected blocks for a synthetic task.
12. Plan index row.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_profiles.py` | `test_twin_update_profile_is_registered_at_import` | Importing `llm_client.workflow.profiles` registers `twin_update`. |
| `tests/test_workflow_profiles.py` | `test_twin_update_plan_review_has_pcm_and_rubric_fields` | Schema accepts the four new lists and a verdict-only payload. |
| `tests/test_workflow_profiles.py` | `test_twin_update_implement_review_has_signoff_axes_claim` | Implement schema accepts a populated SignoffAxesClaim and a regression. |
| `tests/test_workflow_profiles.py` | `test_pcm_layer_finding_requires_evidence_path` | Groundedness — no ungrounded PCM findings. |
| `tests/test_workflow_profiles.py` | `test_twin_update_addendum_mentions_pcm_layers_and_rubric` | Reviewer prompt text surfaces the layer names and rubric axis vocabulary. |
| `tests/test_workflow_profiles.py` | `test_twin_update_context_loader_reads_task_extras` | Loader picks up `customer`, `ai`, `ticket_id`, `complaint_text`, `customer_constraints` keys from `task["extra"]`. |
| `tests/test_workflow_duet.py` | `test_duet_task_accepts_extra_field` | DuetTask round-trips `extra={"customer": "tony", ...}` without schema rejection. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_profiles.py` | Registry + generic + plan_doc_review behavior unchanged. |
| `tests/test_workflow_duet.py` | Chassis regression including new DuetTask.extra. |
| `tests/test_cli_duet.py` | CLI threading still works (twin_update is just another registry entry from the CLI's perspective). |

---

## Acceptance Criteria

- [ ] `pytest tests/test_workflow_profiles.py tests/test_workflow_duet.py tests/test_workflow_builder.py tests/test_workflow_context_config.py tests/test_agents.py::TestBuildAgentOptions tests/test_agents.py::TestWorkspaceKwargAliasing tests/test_cli_smoke.py tests/test_cli_duet.py -q` exits 0.
- [ ] `list_task_families()` returns a sorted list including `twin_update`.
- [ ] `get_task_family("twin_update").plan_review_schema` accepts a `verdict=pass` payload with all four specialized list fields populated (PCM findings, rubric misses, proof gaps, scope violations).
- [ ] `_PLAN_REVIEW_ADDENDUM` contains every PCM layer name (5), every Axis B / B-prompt / C state name (6+5+3=14), and all five hard-stop overclaim rules verbatim from `twin_fidelity_signoff_rubric.md:182-186`. Drift caught automatically by `test_twin_update_addendum_mentions_pcm_layers_and_rubric` iterating every Literal value.
- [ ] `DuetTask(workspace_path=..., extra={"customer": "x"})` validates and round-trips through `model_dump()`.
- [ ] CLI flags routed through `_build_task_extras`: `--customer`, `--ai`, `--ticket-id`, `--complaint-file`, `--customer-constraints`, `--published-prod-qa-artifact`. All optional; all flow into `task["extra"]` where the twin_update profile's `context_loader` consumes them.

---

## Notes

**Design decisions**

- **Library-owned for v1, with a documented escape route.** Plan #31's "domain profiles live in consumer repos" framing is the long-term shape, but it requires adding `--profile-module` to the CLI before any domain profile can register from outside `llm_client`. That CLI work is real but tangential to validating the twin_update schema design. Pragmatic compromise: ship twin_update under `llm_client.workflow.profiles.twin_update` now, add the loader flag in a separate slice if and when a second domain profile (e.g. eval_audit) needs to live consumer-side.
- **`DuetTask.extra: dict[str, Any]`** rather than per-profile `DuetTask` subclasses. Subclassing the task type would force the chassis to dispatch on task type; an `extra` dict keeps the chassis profile-agnostic and matches how the `task` already flows as a plain dict through state.
- **Literal types for PCM layers and rubric axes**, not free-form strings. Catches typos at validation time and makes the schema self-documenting. Trade-off: when the rubric authority gains a new Axis B state, the Literal needs a code update — but the rubric file already lists the canonical states under `proposed_future_renames` for any forthcoming changes, so the cadence is manageable.
- **Reviewer declares `signoff_axes_claim`, chassis doesn't infer.** The rubric's hard-stop rules ("never call a customer-facing behavior ticket `done` from evals alone") are about *claim discipline*, not auto-detection. Making the reviewer write the axes claim makes that claim falsifiable later.
- **`evidence_path` required on every typed finding model.** Same groundedness contract as Plan #30: a reviewer that can't cite shouldn't emit a structured finding; downgrade to a free-text `unverified_claims[]` entry inherited from `PlanReview`.

**Risks**

- **PCM v2 doc lives in `reference/experimental_garbage/`.** That's a workspace-organizational signal that the doc may not be fully canonical. The 5-layer model itself is stable team vocabulary (Brian + Ian + Bridget contributions per the doc header), but if the team renames or splits a layer, the profile's `Literal` will need to track. Minor risk — the layer names have been stable since at least 2026-04.
- **Rubric authority has multiple axes and a 6th Axis B state (`live_traffic_no_regression_observed`) that requires automation that doesn't exist yet.** The profile encodes the level vocabulary regardless; the reviewer can use it as a *claim* even when the automation is pending. Matches the rubric file's own framing.
- **First customer dry-run is gated on Brian picking a closed Maya CLI ticket.** Until that happens, the profile is unvalidated against real artifacts. Offline schema tests confirm shape, not domain fidelity. The dogfood pattern (run the profile, see what it catches, fix gaps) is the real validation path and waits for a real ticket.
- **`context_loader` is a stub.** The full version walks the customer clone, pulls the Linear ticket comment thread, loads the published-prod text-chat QA artifact if present. That's a meaningful chunk of code and would conflate schema design with file-loading logic. Stub-only v1 lets the schema land cleanly; the loader can grow with real-task evidence.

**Follow-ups not in scope**

- `--profile-module` CLI flag for consumer-loaded profiles.
- Filesystem walk in `_load_twin_context_pack` against `clones/latest_prompts/ais-<customer>-<ai>`.
- Per-layer PCM atom catalogue (signal-density tables, etc.).
- Linear-ticket integration in the context loader.
- `eval_audit` profile.
- System-improvement meta-duet that consumes a corpus of `signoff.json` from prior runs.
