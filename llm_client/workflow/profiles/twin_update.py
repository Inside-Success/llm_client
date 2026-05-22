"""The ``twin_update`` duet profile.

Specialized for customer-twin prompt/KB update tickets. Adds reviewer fields
that score against:

- **PCM v2's 5 layers** (Knowledge / Voice / Reasoning / Values+Boundaries /
  Emotional). A twin edit that fixes Voice but breaks Reasoning is the kind
  of cross-layer regression that generic review buckets lose.
- **Twin Fidelity signoff rubric axes** — Axis B (proof depth), Axis B-prompt
  (prompt-only sub-axis), Axis C (claim breadth). Reviewers can't silently
  conflate `regression_signal_only` with `prod_verified`.
- **Customer-twin proof authority contract** — every claim about current
  behavior must trace to personal reproduction; missing authority artifacts
  are blocking by default.
- **Scope vs. constraints** — customer-specific constraints carried in the
  task that the reviewer should refuse to violate.

Implement-side review adds `signoff_axes_claim`: the reviewer must declare
which Axis B / B-prompt / C levels the change has actually earned, plus
flag overclaim risk. This makes the rubric's hard-stop rules (never call a
customer-facing behavior ticket "done" from evals alone, etc.) auditable.

Authority sources encoded here:
- ``workspace/docs/references/twin_fidelity_signoff_rubric.md`` for axis vocabulary
- ``reference/experimental_garbage/pcm-v1-working-set/vision/pcm_v2_full.md`` for layers
- root ``AGENTS.md`` Customer-twin proof and authority contract section
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from llm_client.workflow.duet import ImplementReview, PlanReview
from llm_client.workflow.duet_base import TaskFamily
from llm_client.workflow.duet_registry import register_task_family


# ---------------------------------------------------------------------------
# Authority vocabulary (mirrored exactly from the rubric/PCM authority files)
# ---------------------------------------------------------------------------

PcmLayer = Literal[
    "Knowledge",
    "Voice",
    "Reasoning",
    "Values and Boundaries",
    "Emotional",
]

# Axis B — proof depth (full-twin). Per twin_fidelity_signoff_rubric.md:24-77.
AxisB = Literal[
    "regression_signal_only",
    "narrowly_validated",
    "robustly_verified",
    "qa_ready",
    "prod_verified",
    "live_traffic_no_regression_observed",
]

# Axis B-prompt — prompt-only sub-axis. Per twin_fidelity_signoff_rubric.md:141-178.
AxisBPrompt = Literal[
    "prompt_unverified",
    "prompt_dev_smoke_only",
    "prompt_robustly_verified",
    "prompt_prod_cleared",
    "prompt_ready_to_close",
]

# Axis C — claim breadth. Per twin_fidelity_signoff_rubric.md:78-104.
AxisC = Literal[
    "candidate_fix",
    "complaint_flow_cleared",
    "broadly_complete",
]

Severity = Literal["info", "warn", "high"]


# ---------------------------------------------------------------------------
# Plan-review specialized findings
# ---------------------------------------------------------------------------


class PcmLayerFinding(BaseModel):
    """A finding scoped to one PCM v2 personality layer.

    ``evidence_path`` is required so PCM claims are falsifiable: a reviewer
    saying "Layer 3 reasoning will regress" without a citation is opinion.
    """

    model_config = ConfigDict(extra="forbid")

    layer: PcmLayer
    finding: str
    severity: Severity = "warn"
    evidence_path: str


class TwinFidelityRubricMiss(BaseModel):
    """A way the proposed change fails to meet a Twin Fidelity rubric item.

    ``axis`` and ``item`` together identify the rubric atom (e.g.
    ``axis="axis_b_proof_depth"``, ``item="qa_ready"``). Reviewers should
    use this when the plan claims a level it hasn't actually earned.
    """

    model_config = ConfigDict(extra="forbid")

    axis: Literal[
        "axis_b_proof_depth",
        "axis_b_prompt",
        "axis_c_claim_breadth",
        "row_status",
    ]
    item: str
    why_missed: str
    suggested_remediation: str = ""


class ProofAuthorityGap(BaseModel):
    """A missing authority artifact that blocks a claim.

    Enforces the root ``AGENTS.md`` customer-twin proof contract: if a
    referenced document, call note, email thread, uploaded file, or
    equivalent authority artifact cannot be retrieved, treat that as
    blocking by default.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str
    missing_artifact: str
    why_blocking: str
    narrower_claim_still_safe: str = ""


class ScopeViolation(BaseModel):
    """A proposed change that violates an explicit customer constraint."""

    model_config = ConfigDict(extra="forbid")

    proposed_change: str
    customer_constraint_violated: str
    evidence_path: str


class TwinUpdatePlanReview(PlanReview):
    """Plan reviewer schema specialized for twin update tickets."""

    model_config = ConfigDict(extra="forbid")

    pcm_layer_findings: list[PcmLayerFinding] = Field(default_factory=list)
    twin_fidelity_rubric_misses: list[TwinFidelityRubricMiss] = Field(default_factory=list)
    proof_authority_gaps: list[ProofAuthorityGap] = Field(default_factory=list)
    scope_violations: list[ScopeViolation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Implement-review specialized findings
# ---------------------------------------------------------------------------


class PcmLayerRegression(BaseModel):
    """A PCM v2 layer that the implementation regresses against."""

    model_config = ConfigDict(extra="forbid")

    layer: PcmLayer
    regression: str
    severity: Severity = "warn"
    evidence_path: str


class SignoffAxesClaim(BaseModel):
    """The Axis B / B-prompt / C levels the reviewer believes the change has earned.

    The reviewer declares this; the chassis does not infer. ``overclaim_risk``
    plus ``reason`` capture the rubric's hard-stop discipline (e.g. "evals
    passed but no published-prod replay; do not call prod_verified").
    """

    model_config = ConfigDict(extra="forbid")

    axis_b: AxisB | Literal["not_claimed"] = "not_claimed"
    axis_b_prompt: AxisBPrompt | Literal["not_claimed"] = "not_claimed"
    axis_c: AxisC | Literal["not_claimed"] = "not_claimed"
    overclaim_risk: bool = False
    reason: str = ""


class TwinUpdateImplementReview(ImplementReview):
    """Implementation reviewer schema specialized for twin update tickets."""

    model_config = ConfigDict(extra="forbid")

    pcm_layer_regressions: list[PcmLayerRegression] = Field(default_factory=list)
    signoff_axes_claim: SignoffAxesClaim | None = None
    published_prod_qa_evidence_path: str = ""


# ---------------------------------------------------------------------------
# Prompt addenda
# ---------------------------------------------------------------------------


_PLAN_REVIEW_ADDENDUM = """

## Twin-update review extension

This is a customer-twin prompt/KB update review. Score the plan against the
PCM v2 personality model and the Twin Fidelity signoff rubric in addition to
the generic PlanReview fields.

### PCM v2 layers (use the exact layer names)

- **Knowledge** — what the person knows. Domains, frameworks, knowledge boundaries.
- **Voice** — how they talk. Sentence structure, vocabulary, signature phrases, formality range.
- **Reasoning** — how they think. Problem-solving approach, analogy sourcing, decision frameworks.
- **Values and Boundaries** — what they would and wouldn't do. Topic avoidance, referral patterns, brand alignment.
- **Emotional** — how they connect. Empathy patterns, celebration style, intensity modulation.

For each PCM layer the proposed change touches (or risks touching), emit a
``pcm_layer_findings`` entry with the exact layer name, the finding, severity,
and an ``evidence_path`` citation. Cross-layer regressions (e.g. a Voice fix
that breaks Reasoning depth) are particularly important to flag.

### Twin Fidelity rubric axes

- **Axis B (proof depth)** — ``regression_signal_only`` → ``narrowly_validated`` → ``robustly_verified`` → ``qa_ready`` → ``prod_verified`` → ``live_traffic_no_regression_observed``.
- **Axis B-prompt (prompt-only)** — ``prompt_unverified`` → ``prompt_dev_smoke_only`` → ``prompt_robustly_verified`` → ``prompt_prod_cleared`` → ``prompt_ready_to_close``.
- **Axis C (claim breadth)** — ``candidate_fix`` → ``complaint_flow_cleared`` → ``broadly_complete``.

When the plan claims a level it has not earned, emit a
``twin_fidelity_rubric_misses`` entry with the axis name (lowercase, exactly as
listed above), the item, why it was missed, and a suggested remediation.

### Hard-stop overclaim rules (from twin_fidelity_signoff_rubric.md:182-186)

Flag a rubric miss for any of:
- ``100%`` without ``of N currently covered scenarios on <lane>``
- multiple lanes collapsed into one status line without naming the authoritative lane
- a customer-facing behavior ticket called ``done`` from evals alone
- a source-faithfulness ticket called ``verified`` when the judge never saw the source authority
- a closeout that rests on one long generalized persona scenario as the only signoff proof

### Proof authority contract

Every claim the plan makes about CURRENT customer-twin behavior must trace
to a personal reproduction by the plan's author. Chained inference
(``someone characterized this`` + ``a fix is in flight`` + ``evidence is
days/weeks old``) does not satisfy this. When the plan asserts current
behavior without authority artifacts, emit a ``proof_authority_gaps`` entry
with the claim, the missing artifact, why it blocks the claim, and the
narrower claim that would still be safe.

### Scope vs. constraints

Customer-specific constraints carried in the task (``task.constraints``,
``task.extra.customer_constraints``) are not optional. When the plan
proposes a change that violates one, emit a ``scope_violations`` entry with
the proposed change, the violated constraint, and an evidence_path citation.
""".strip()


_IMPLEMENT_REVIEW_ADDENDUM = """

## Twin-update review extension

This is the implementation review for a customer-twin update. The reviewer
must:

1. Re-check the proposed change against PCM v2's 5 layers and emit
   ``pcm_layer_regressions`` for any layer the implementation worsens
   (Voice fix that flattens Reasoning depth, Values tightening that breaks
   Emotional warmth, etc.). Use the exact layer names: Knowledge, Voice,
   Reasoning, Values and Boundaries, Emotional.

2. Declare a ``signoff_axes_claim`` with the Axis B level (full-twin proof
   depth), Axis B-prompt level (prompt-only sub-axis), and Axis C level
   (claim breadth) that the implementation has actually earned. Use
   ``not_claimed`` when the change scope doesn't reach that axis (e.g.
   prompt-only edits leave Axis B at ``not_claimed`` and use Axis B-prompt).
   Set ``overclaim_risk=true`` with a ``reason`` when evidence is weaker
   than the implementer's narrative implies.

3. Cite ``published_prod_qa_evidence_path`` when the change is prompt-visible
   and the implementer claims ``prompt_prod_cleared`` or ``prompt_ready_to_close``.
   Empty string is acceptable when no such evidence is yet expected.
""".strip()


# ---------------------------------------------------------------------------
# Context loader
# ---------------------------------------------------------------------------


def _load_twin_context_pack(task: dict[str, Any]) -> dict[str, str]:
    """Render twin-update context blocks from ``task["extra"]``.

    Reads optional keys ``customer``, ``ai``, ``ticket_id``, ``complaint_text``,
    ``customer_constraints``, ``published_prod_qa_artifact_path``. Each present
    key becomes a ``## <label>`` block in the reviewer prompt.

    v1 is stub-only: the loader does NOT walk the customer clone or fetch
    Linear comments. Callers stash whatever context they want via
    ``task["extra"]``. The full filesystem-walking loader can grow later
    without breaking the schema.
    """
    extra = task.get("extra") or {}
    blocks: dict[str, str] = {}

    if customer := extra.get("customer"):
        ai = extra.get("ai", "?")
        blocks["Customer twin"] = f"customer={customer} ai={ai}"

    if ticket_id := extra.get("ticket_id"):
        blocks["Linear ticket"] = str(ticket_id)

    if complaint := extra.get("complaint_text"):
        blocks["Customer complaint"] = str(complaint)

    if customer_constraints := extra.get("customer_constraints"):
        if isinstance(customer_constraints, list):
            rendered = "\n".join(f"- {c}" for c in customer_constraints)
        else:
            rendered = str(customer_constraints)
        blocks["Customer constraints"] = rendered

    if qa_artifact := extra.get("published_prod_qa_artifact_path"):
        blocks["Published-prod QA artifact"] = str(qa_artifact)

    return blocks


TWIN_UPDATE_PROFILE = TaskFamily(
    name="twin_update",
    plan_review_schema=TwinUpdatePlanReview,
    implement_review_schema=TwinUpdateImplementReview,
    plan_prompt_addendum="",
    plan_review_prompt_addendum=_PLAN_REVIEW_ADDENDUM,
    implement_prompt_addendum="",
    implement_review_prompt_addendum=_IMPLEMENT_REVIEW_ADDENDUM,
    context_loader=_load_twin_context_pack,
)


register_task_family(TWIN_UPDATE_PROFILE)


__all__ = [
    "PcmLayer",
    "AxisB",
    "AxisBPrompt",
    "AxisC",
    "Severity",
    "PcmLayerFinding",
    "TwinFidelityRubricMiss",
    "ProofAuthorityGap",
    "ScopeViolation",
    "TwinUpdatePlanReview",
    "PcmLayerRegression",
    "SignoffAxesClaim",
    "TwinUpdateImplementReview",
    "TWIN_UPDATE_PROFILE",
]
