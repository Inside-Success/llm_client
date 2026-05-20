# Plan #31: TaskFamily Abstraction for the Duet Chassis

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #30 (chassis verified-correct)
**Blocks:** Future twin_update / eval_audit profiles

---

## Gap

**Current:** The duet chassis bakes generic reviewer schemas (`PlanReview`, `ImplementReview`) and prompt text into `duet.py`. Any caller that wants domain-specific reviewer fields (PCM layers, Twin Fidelity rubric items, eval-design-review framework, plan-doc TEMPLATE.md compliance) has to fork the chassis or stuff everything into the generic `unverified_claims` / `nits` buckets. Plan #29's self-review surfaced this: the generic schema worked for plan-doc review but lost fidelity ("scope_creep_findings was empty because the plan IS the scope; TEMPLATE.md compliance had to be jammed into nits").

**Target:** Extract a `TaskFamily` extension point so the chassis owns wiring + routing + persistence while profiles own:
- Reviewer schemas (subclasses of `PlanReviewBase` / `ImplementReviewBase`)
- Prompt addenda (extra system + user context appended to the base prompt)
- Context loaders (functions that pull profile-specific authority artifacts into the prompt)

Ship two library-owned profiles to validate the abstraction:
- `generic` — encodes today's behavior as an explicit profile (regression-free default)
- `plan_doc_review` — first specialized profile, with schema fields for TEMPLATE.md section coverage, reference verification status, and acceptance-criterion-quality findings

Domain profiles (`twin_update`, `eval_audit`) stay out of scope for #31 — they'll live in workspace skills or consumer repos and register against the same chassis.

**Why:** Without profiles, every domain task either degrades to the generic schema (losing reviewer fidelity) or forks the chassis (losing observability + chassis fixes). With profiles, the chassis stays small and well-tested while domain knowledge accretes in modular surfaces. Plan #29 + #30 hardened a generic chassis that's safe to split.

---

## References Reviewed

- `runs/plan-29-self-review/plan_review.json` — the original evidence that the generic schema is workable but loses fidelity for plan-doc review. The reviewer used `nits` for findings that wanted a more specific field (TEMPLATE.md compliance, reference-verification status).
- `runs/plan-30-review-v2/plan_review.json` — verdict `pass` confirming the chassis is correct after Plan #30 followup; Plan #31 splits this verified chassis.
- `llm_client/workflow/duet.py:129-216` — current `PlanReview` / `ImplementReview` schemas that become the `generic` profile.
- `llm_client/workflow/duet.py:271-428` — prompt builders that become "base prompts + addendum" after the refactor.
- `llm_client/workflow/duet.py:465-559` — node factories that need to learn about `TaskFamily` to pick the right schema + prompt addendum.
- `llm_client/workflow/duet.py:631-723` — `build_duet_workflow()` that gets the `task_family="generic"` kwarg.
- `llm_client/cli/duet.py:99-228` — CLI handler that gets a `--task-family` flag.

---

## Files Affected

- `llm_client/workflow/duet_base.py` (create) — `PlanReviewBase`, `ImplementReviewBase`, `TaskFamily` dataclass.
- `llm_client/workflow/duet_registry.py` (create) — `register_task_family`, `get_task_family`, `list_task_families`.
- `llm_client/workflow/profiles/__init__.py` (create) — registers built-in profiles at import time.
- `llm_client/workflow/profiles/generic.py` (create) — encodes today's behavior as the `generic` profile.
- `llm_client/workflow/profiles/plan_doc_review.py` (create) — `PlanDocPlanReview` schema with `template_section_misses`, `references_unverified`, `acceptance_criteria_unmeasurable`; tuned prompt addendum.
- `llm_client/workflow/duet.py` (modify) — make `PlanReview` / `ImplementReview` inherit from base; add `task_family: str = "generic"` param to `build_duet_workflow`; thread the family through node factories so schemas and prompt addenda are profile-resolved.
- `llm_client/workflow/__init__.py` (modify) — export new types.
- `llm_client/cli/duet.py` (modify) — `--task-family` flag (default `"generic"`).
- `tests/test_workflow_profiles.py` (create) — registry behavior, generic preserves existing behavior, plan_doc_review uses its own schema.
- `tests/test_workflow_duet.py` (modify) — replace one happy-path test with an explicit `task_family="generic"` assertion so the default behavior is locked in.
- `tests/test_cli_smoke.py` (modify) — still covered by the existing `duet-review --help` smoke; no new entry needed.
- `docs/plans/31_task_family_abstraction.md` (this file).
- `docs/plans/CLAUDE.md` (modify) — append index row.

Out of scope (deliberately):
- `twin_update` and `eval_audit` profiles — they consume the registry but live in workspace skills or consumer repos. Building them in #31 would conflate chassis design with domain-specific schema work.
- Profile-specific routers (e.g. plan_doc_review treating `revise` differently from generic). Routers stay uniform; profiles only add fields, they don't change control flow.
- A "profile inheritance" mechanism so domain profiles can extend `generic`. Single-level profiles only; if duplication shows up, address with a base class within the profile module.
- Versioning profiles (`plan_doc_review@v2`). Single name per registry entry.

---

## Plan

### Steps

1. `duet_base.py`: `PlanReviewBase(BaseModel)` with `verdict: DuetVerdict`, `reviewer_summary: str = ""`, `reviewer_model: str = ""`. Same shape for `ImplementReviewBase`. `TaskFamily` as a frozen dataclass holding `name`, `plan_review_schema: type[PlanReviewBase]`, `implement_review_schema: type[ImplementReviewBase]`, four prompt-addendum strings (system/user × plan/implement reviewer), and `context_loader: Callable[[dict], dict[str, str]]` with an empty-dict default.
2. `duet_registry.py`: module-level `_REGISTRY: dict[str, TaskFamily]`. `register_task_family(family)` raises if name already registered. `get_task_family(name)` raises if missing. `list_task_families()` returns names.
3. `profiles/generic.py`: define `GenericPlanReview(PlanReviewBase)` and `GenericImplementReview(ImplementReviewBase)` carrying today's fields. Construct the `TaskFamily` with empty addenda + empty context loader. Register at import.
4. `profiles/plan_doc_review.py`: `PlanDocPlanReview(PlanReviewBase)` with extra fields `template_section_misses: list[str]`, `references_unverified: list[CitationRef]`, `acceptance_criteria_unmeasurable: list[str]`, plus the generic blocker/nit lists for backward compat. Reuse `GenericImplementReview` since most implementation reviews of a plan-doc revision look the same. Prompt addenda say "this is a plan-doc review against TEMPLATE.md: Gap, References Reviewed, Files Affected, Plan, Required Tests, Acceptance Criteria, Notes; flag missing sections; verify cited file:line ranges or list them as unverified." Register at import.
5. `profiles/__init__.py`: import the two modules so registration happens on `from llm_client.workflow.profiles import *` (or whenever the workflow package loads).
6. `duet.py`: re-parent `PlanReview` and `ImplementReview` to `PlanReviewBase` / `ImplementReviewBase` (no field changes — pure inheritance). Add `task_family: str = "generic"` kwarg to `build_duet_workflow`. Thread `family = get_task_family(task_family)` and pass it to `_make_plan_node` / `_make_plan_review_node` / `_make_implement_node` / `_make_implement_review_node`. Each node resolves `family.plan_review_schema` (etc.) and concatenates `family.*_prompt_addendum` into the user message. The chassis's base prompt still owns the response-format contract and the schema-emission block.
7. `duet.py` prompt builders gain an optional `family: TaskFamily | None = None` param; when present, the user message gains `## <label>` blocks from `family.context_loader(task)` and the `family.*_prompt_addendum` suffix.
8. `workflow/__init__.py`: export `PlanReviewBase`, `ImplementReviewBase`, `TaskFamily`, `register_task_family`, `get_task_family`, `list_task_families`. Import the profiles subpackage so registration happens on `from llm_client.workflow import build_duet_workflow`.
9. `cli/duet.py`: add `--task-family` flag (default `"generic"`); resolve via registry; pass the family schema to `call_llm_structured` and the addenda to the prompt builders.
10. `tests/test_workflow_profiles.py`: registry registers/gets/lists; `generic` carries the today fields; `plan_doc_review` has `template_section_misses` and rejects an `unknown_task_family` name with a clear error.
11. `tests/test_workflow_duet.py`: extend one happy-path test to assert `task_family="generic"` is the default; add a test that passes `task_family="plan_doc_review"` and verifies the prompt addendum reaches the LLM stub seam.
12. Plan index update.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_workflow_profiles.py` | `test_registry_register_and_get` | `register_task_family` + `get_task_family` round-trip. |
| `tests/test_workflow_profiles.py` | `test_registry_get_missing_raises` | Unknown name surfaces a clear error. |
| `tests/test_workflow_profiles.py` | `test_registry_double_register_raises` | Duplicate name is a programmer error, not silent overwrite. |
| `tests/test_workflow_profiles.py` | `test_generic_profile_is_registered_at_import` | `from llm_client.workflow.profiles` triggers `generic` registration. |
| `tests/test_workflow_profiles.py` | `test_plan_doc_review_schema_has_template_sections_field` | Specialized schema has the new fields and still validates a minimal `verdict=pass` payload. |
| `tests/test_workflow_duet.py` | `test_duet_default_task_family_is_generic` | Existing happy-path uses the `generic` profile; behavior unchanged. |
| `tests/test_workflow_duet.py` | `test_duet_with_plan_doc_review_profile_uses_specialized_schema` | Passing `task_family="plan_doc_review"` to the builder routes the structured call to the specialized schema. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_workflow_duet.py::*` (12 + new) | Chassis regression; new inheritance must not break the existing fields. |
| `tests/test_workflow_builder.py` | LangGraph wiring unchanged. |
| `tests/test_agents.py::TestWorkspaceKwargAliasing` | cwd aliasing layer unchanged. |
| `tests/test_cli_smoke.py` | CLI registration unchanged. |

---

## Acceptance Criteria

- [ ] All required tests pass.
- [ ] `generic` profile is the default; existing duet calls behave identically.
- [ ] `plan_doc_review` profile is registered at import and surfaces `template_section_misses` + `references_unverified` + `acceptance_criteria_unmeasurable` in the schema.
- [ ] Unknown `task_family` name raises a clear error (no silent fallback to generic).
- [ ] CLI `duet-review --task-family <name>` accepts the flag and threads to the call.

---

## Notes

**Design decisions**

- **Profile via dataclass, not Pydantic.** Schemas need to be class objects passed around; Pydantic-of-Pydantic-types adds friction with no benefit. A frozen dataclass is the right shape.
- **Addendum, not full prompt override.** Profile contributes extra system + user blocks. Chassis still owns the base prompt + response-format + schema-emission contract. Reviewer-output-format drift gets caught by chassis tests; profiles can't break it accidentally.
- **Registry is global, not per-builder-call.** Imports register profiles once. Callers reference by name (`task_family="plan_doc_review"`). Cheaper than threading a profile *object* through the builder.
- **`plan_doc_review` reuses `GenericImplementReview`.** A plan-doc revision implementation review looks like a regular code-review at the implementation layer; only the plan-review side benefits from specialization right now.
- **Schemas inherit, not compose.** A `PlanDocPlanReview` IS-A `PlanReviewBase`; it adds fields but doesn't wrap. The router only reads `verdict`, so subclass fields don't break routing.

**Risks**

- **Profile registration timing.** If a consumer module forgets to import `llm_client.workflow.profiles`, `get_task_family("generic")` will raise. Mitigated by `llm_client.workflow.__init__` importing the profiles subpackage so any `from llm_client.workflow import build_duet_workflow` also registers built-ins.
- **Schema-emission JSON-schema drift.** The chassis prompt embeds `json.dumps(PlanReview.model_json_schema())`. After Plan #31 it embeds the family-resolved schema. If the schema gets bigger (more fields) the prompt grows; large schemas can slow the LLM down. The `plan_doc_review` schema is small enough not to be an issue, but worth watching when domain profiles land.
- **Pydantic discriminated-union temptation.** Easy to think `verdict: Literal["pass", "revise", "block"]` + `extensions: dict` is "simpler." It's not — losing static typing on profile-specific fields makes the schema enforcement meaningless. Stick with subclass inheritance.

**Follow-ups not in scope**

- Domain profiles (`twin_update`, `eval_audit`). They consume the registry from outside `llm_client`.
- A `--list-task-families` flag on the CLI.
- Profile-specific routers / cycle caps / context-pack-size limits.
- Schema versioning.
