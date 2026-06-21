"""Standalone adversarial-review schemas, profiles, and prompt construction.

The CLI is intentionally a thin adapter over this module. Keeping the schema
and profile registry here lets background reviews and future review-cycle runs
share one canonical JSON contract instead of growing parallel review
taxonomies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client.workflow.duet import (
    ContractViolation,
    CorrectnessFinding,
    Nit,
    UnverifiedClaim,
)

AdversarialVerdict = Literal["pass", "concerns", "blocker"]
ReviewAnnotationKind = Literal["optimum_gap", "spurious", "uncertain"]
ReviewSchemaVersion = Literal["1", "2"]


class ReviewAnnotation(BaseModel):
    """Profile-specific rationale linked to canonical review findings."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str
    kind: ReviewAnnotationKind
    claim: str
    evidence_path: str | None = None
    linked_finding_index: int | None = Field(default=None, ge=0)
    validity_loss_without_change: str = ""
    why_rejected_or_uncertain: str = ""

    @model_validator(mode="after")
    def _validate_kind_contract(self) -> "ReviewAnnotation":
        if self.kind == "optimum_gap":
            if self.linked_finding_index is None:
                raise ValueError("optimum_gap requires linked_finding_index")
            if not self.validity_loss_without_change.strip():
                raise ValueError("optimum_gap requires validity_loss_without_change")
        elif not self.why_rejected_or_uncertain.strip():
            raise ValueError(f"{self.kind} requires why_rejected_or_uncertain")
        return self


class AdversarialReviewV1(BaseModel):
    """Version-1 standalone review schema.

    This preserves the original ``review-artifact`` JSON shape for strict
    consumers that use ``extra='forbid'`` mirror schemas.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_label: str
    verdict: AdversarialVerdict
    summary: str
    correctness_findings: list[CorrectnessFinding] = Field(default_factory=list)
    contract_violations: list[ContractViolation] = Field(default_factory=list)
    nits: list[Nit] = Field(default_factory=list)
    unverified_claims: list[UnverifiedClaim] = Field(default_factory=list)
    scope_drift_findings: list[str] = Field(default_factory=list)
    reviewer_model: str = ""


class AdversarialReview(AdversarialReviewV1):
    """Version-2 standalone review schema with profile annotations."""

    profile_annotations: list[ReviewAnnotation] = Field(default_factory=list)


class ReviewAnnotationResponse(BaseModel):
    """Permissive LLM-facing profile annotation parsed before repair.

    Provider-side structured decoding does not enforce Pydantic validators such
    as "uncertain requires why_rejected_or_uncertain". This boundary model keeps
    live malformed annotations observable so they can be repaired or routed to
    discussion instead of crashing the whole review cycle.
    """

    model_config = ConfigDict(extra="ignore")

    annotation_id: str = Field(default="", description="Stable annotation identifier assigned by the reviewer.")
    kind: str = Field(
        default="",
        description="One of optimum_gap, spurious, or uncertain. Unknown values are routed to discussion.",
    )
    claim: str = Field(default="", description="Profile-specific review claim.")
    evidence_path: str | None = Field(
        default=None,
        description="Optional evidence locator for the profile annotation.",
    )
    linked_finding_index: int | None = Field(
        default=None,
        description="For optimum_gap only: non-negative index into correctness_findings; booleans are invalid.",
    )
    validity_loss_without_change: str = Field(
        default="",
        description="For optimum_gap only: what the artifact gets wrong without this change.",
    )
    why_rejected_or_uncertain: str = Field(
        default="",
        description="Required rationale for spurious and uncertain annotations.",
    )


class AdversarialReviewResponse(AdversarialReviewV1):
    """Permissive v2 LLM response shape normalized into ``AdversarialReview``."""

    model_config = ConfigDict(extra="ignore")

    profile_annotations: list[ReviewAnnotationResponse] = Field(default_factory=list)


@dataclass(frozen=True)
class ReviewProfile:
    """Prompt/schema extension for standalone artifact review."""

    name: str
    system_addendum: str = ""
    user_addendum: str = ""
    requires_schema_v2: bool = False


_REGISTRY: dict[str, ReviewProfile] = {}


def register_review_profile(profile: ReviewProfile) -> None:
    """Register a standalone review profile by unique name."""
    if not profile.name.strip():
        raise ValueError("ReviewProfile.name must be non-empty")
    if profile.name in _REGISTRY:
        raise ValueError(f"Review profile already registered: {profile.name}")
    _REGISTRY[profile.name] = profile


def get_review_profile(name: str) -> ReviewProfile:
    """Resolve a registered review profile or raise a clear error."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"Unknown review profile {name!r}. Known: {known}") from exc


def list_review_profiles() -> list[str]:
    """Return registered standalone review profile names."""
    return sorted(_REGISTRY)


def adversarial_review_schema(
    version: ReviewSchemaVersion = "1",
) -> type[AdversarialReviewV1]:
    """Return the standalone review schema for ``version``."""
    if version == "1":
        return AdversarialReviewV1
    if version == "2":
        return AdversarialReview
    raise ValueError(f"Unknown review schema version: {version!r}")


def adversarial_review_response_schema(
    version: ReviewSchemaVersion = "1",
) -> type[AdversarialReviewV1]:
    """Return the schema used to parse live LLM output for ``version``."""
    if version == "1":
        return AdversarialReviewV1
    if version == "2":
        return AdversarialReviewResponse
    raise ValueError(f"Unknown review schema version: {version!r}")


def normalize_adversarial_review_response(
    payload: AdversarialReviewV1 | dict[str, Any],
) -> AdversarialReviewV1:
    """Normalize permissive live review output into the canonical schema."""
    data = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
    if "profile_annotations" not in data:
        return AdversarialReviewV1.model_validate(data)

    normalized: list[dict[str, Any]] = []
    for index, raw_item in enumerate(data.get("profile_annotations") or [], start=1):
        if isinstance(raw_item, BaseModel):
            item = raw_item.model_dump()
        elif isinstance(raw_item, dict):
            item = dict(raw_item)
        else:
            item = {
                "annotation_id": f"annotation_{index}",
                "kind": "uncertain",
                "claim": str(raw_item),
                "why_rejected_or_uncertain": "Malformed profile annotation was not an object.",
            }

        item["annotation_id"] = str(item.get("annotation_id") or f"annotation_{index}")
        item["claim"] = str(item.get("claim") or "Malformed profile annotation")
        kind = str(item.get("kind") or "uncertain")
        item["kind"] = kind

        if kind == "optimum_gap":
            linked = item.get("linked_finding_index")
            validity = str(item.get("validity_loss_without_change") or "")
            if type(linked) is not int or linked < 0 or not validity.strip():
                item["kind"] = "uncertain"
                item["linked_finding_index"] = None
                item["validity_loss_without_change"] = ""
                item["why_rejected_or_uncertain"] = (
                    "Invalid optimum_gap annotation omitted a non-negative "
                    "linked_finding_index or validity_loss_without_change; "
                    "routed to discussion instead of auto-apply."
                )
        elif kind in {"spurious", "uncertain"}:
            if not str(item.get("why_rejected_or_uncertain") or "").strip():
                item["why_rejected_or_uncertain"] = (
                    f"Reviewer omitted why_rejected_or_uncertain for {kind}; "
                    "routed to discussion with repair note."
                )
        else:
            item["kind"] = "uncertain"
            item["linked_finding_index"] = None
            item["validity_loss_without_change"] = ""
            item["why_rejected_or_uncertain"] = (
                f"Unknown profile annotation kind {kind!r}; routed to discussion."
            )
        normalized.append(item)

    data["profile_annotations"] = normalized
    return AdversarialReview.model_validate(data)


def resolve_review_schema_version(
    profile: ReviewProfile,
    requested: str = "auto",
) -> ReviewSchemaVersion:
    """Resolve a schema-version request for ``profile``."""
    if requested == "auto":
        return "2" if profile.requires_schema_v2 else "1"
    if requested not in {"1", "2"}:
        raise ValueError("review schema version must be one of: auto, 1, 2")
    if profile.requires_schema_v2 and requested == "1":
        raise ValueError(
            f"Review profile {profile.name!r} requires review schema version 2"
        )
    return requested  # type: ignore[return-value]


def build_review_prompt(
    artifact_label: str,
    artifact_body: str,
    context_body: str,
    response_schema: type[BaseModel],
    profile: ReviewProfile | None = None,
) -> list[dict[str, Any]]:
    """Build messages for a standalone adversarial review."""
    selected_profile = profile or get_review_profile("generic")
    schema_name = response_schema.__name__
    system = (
        "You are an adversarial reviewer. Your job is to find what's WRONG "
        "with the artifact below, not to validate it. The author of the "
        "artifact is biased toward their own work; your role is the opposite "
        "bias — look for bugs, missed edge cases, contradictions with stated "
        "constraints, unverifiable claims, and scope drift. Inspect the "
        "workspace via your file-reading tools to verify any claim against "
        "actual code. Do not edit any files."
    )
    if selected_profile.system_addendum.strip():
        system = f"{system}\n\n{selected_profile.system_addendum.strip()}"

    user_parts = [
        f"## Artifact under review: {artifact_label}",
        "",
        "## Context (what the author was attempting)",
        context_body or "(no context provided — review on intrinsic merit)",
        "",
        "## Artifact body",
        artifact_body,
        "",
        f"Return a {schema_name} JSON object. Verdict must be one of: "
        "pass, concerns, blocker. Groundedness rules: every "
        "correctness_findings entry MUST have file_path (str) and line (int); "
        "every contract_violations entry MUST have constraint, violation, "
        "and evidence_path. If you cannot cite a specific file:line, use "
        "unverified_claims (UnverifiedClaim with claim + reason_unverified) "
        "or a free-text scope_drift_findings entry instead. Use 'blocker' "
        "verdict only when at least one finding would break correctness or "
        "a stated constraint. Use 'concerns' when at least one significant "
        "correctness or contract issue exists but none is catastrophic. Use 'pass' when "
        "the artifact is shippable as-is (nits/unverified may still appear).",
    ]
    if selected_profile.user_addendum.strip():
        user_parts.extend(
            ["", "## Review profile instructions", selected_profile.user_addendum.strip()]
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def render_quality_optimal_sections(review: AdversarialReviewV1) -> str:
    """Render quality-optimal review sections from canonical JSON."""
    payload = review.model_dump()
    annotations = payload.get("profile_annotations", []) or []
    optimum_by_index = {}
    duplicate_optimum = []
    for item in annotations:
        if item.get("kind") != "optimum_gap" or item.get("linked_finding_index") is None:
            continue
        index = item["linked_finding_index"]
        if index in optimum_by_index:
            duplicate_optimum.append(item)
            continue
        optimum_by_index[index] = item
    spurious = [item for item in annotations if item.get("kind") == "spurious"]
    uncertain = [item for item in annotations if item.get("kind") == "uncertain"]

    lines = [
        f"Verdict: {payload['verdict']}",
        "",
        "[DEFECT]",
    ]
    for finding in payload.get("contract_violations", []):
        lines.append(f"- {finding['constraint']}: {finding['violation']}")
    for idx, finding in enumerate(payload.get("correctness_findings", [])):
        if idx not in optimum_by_index and finding.get("severity") == "high":
            lines.append(f"- {finding['severity']}: {finding['claim']}")

    lines.extend(["", "[OPTIMUM-GAP]"])
    correctness_findings = payload.get("correctness_findings", [])
    for idx, annotation in optimum_by_index.items():
        if idx >= len(correctness_findings):
            continue
        finding = correctness_findings[idx]
        lines.append(
            "- "
            + finding["claim"]
            + " What is wrong without it: "
            + annotation["validity_loss_without_change"]
        )

    lines.extend(["", "[SPURIOUS]"])
    for annotation in spurious:
        lines.append(
            "- "
            + annotation["claim"]
            + " Rejected because: "
            + annotation["why_rejected_or_uncertain"]
        )

    lines.extend(["", "[UNCERTAIN]"])
    for claim in payload.get("unverified_claims", []):
        lines.append(f"- {claim['claim']}: {claim['reason_unverified']}")
    for annotation in uncertain:
        lines.append(
            "- "
            + annotation["claim"]
            + " Uncertain because: "
            + annotation["why_rejected_or_uncertain"]
        )
    for annotation in duplicate_optimum:
        lines.append(
            "- "
            + annotation["claim"]
            + " Uncertain because: duplicate optimum_gap linked_finding_index."
        )
    return "\n".join(lines)


_QUALITY_OPTIMAL_SYSTEM_ADDENDUM = (
    "You are reviewing a methodology white paper whose explicit purpose is to "
    "describe the quality-optimal architecture for its task, with compute cost "
    "treated as unconstrained. Do not recommend cutting, simplifying, gating, "
    "cheapening, or staging anything to save cost, time, latency, or effort. "
    "Also do not recommend adding machinery merely because it is conventional "
    "or more complete. Every proposed change must improve correctness or "
    "fidelity to the actual optimum."
)

_QUALITY_OPTIMAL_USER_ADDENDUM = (
    "Classify feedback through the canonical AdversarialReview schema. Put "
    "wrong claims, contradictions, and incoherence in correctness_findings or "
    "contract_violations. Put genuine optimum gaps in correctness_findings and "
    "link them with profile_annotations kind=optimum_gap, including the "
    "concrete validity loss in validity_loss_without_change. Put tempting but "
    "rejected additions in profile_annotations kind=spurious. Put uncertain "
    "items in unverified_claims or profile_annotations kind=uncertain. "
    "Explicitly check internal coherence between definitions, worked examples, "
    "and sections. Rank high-impact defects first. Distinguish a useful "
    "epistemic tension from an error to remove."
)


def _register_builtins() -> None:
    if "generic" not in _REGISTRY:
        register_review_profile(ReviewProfile(name="generic"))
    if "quality_optimal_whitepaper" not in _REGISTRY:
        register_review_profile(
            ReviewProfile(
                name="quality_optimal_whitepaper",
                system_addendum=_QUALITY_OPTIMAL_SYSTEM_ADDENDUM,
                user_addendum=_QUALITY_OPTIMAL_USER_ADDENDUM,
                requires_schema_v2=True,
            )
        )


_register_builtins()
