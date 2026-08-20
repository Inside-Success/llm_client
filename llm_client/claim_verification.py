"""Graduated-severity verification of atomic claims against cited evidence.

A claim-verification judge decomposes one text into atomic claims and asks, per
claim, whether the cited evidence supports it. The failure mode this module
exists to prevent is a *binary* answer: with only "entailed" and "overstated",
an unremarkable adjective and an invented causal link are the same verdict, so
prose that no reader would call wrong gets blocked alongside prose that is.

This module supplies the three parts a binary judge lacks:

1. A graduated severity vocabulary (:data:`SEVERITY_RUBRIC_NAME`), expressed as
   an ordinary categorical rubric so tiers are named, versioned and reviewable
   like any other rubric in :mod:`llm_client.rubric_registry`.
2. Per-claim *multi-support* provenance. A claim whose parts rest on different
   kinds of support — a historical observation joined to a computed result —
   records one :class:`ClaimSupport` per part instead of being forced to pick a
   single regime for the whole span. Forcing a single choice is what makes such
   claims flip verdict between otherwise identical runs.
3. Deterministic post-judgment verification. The judge's citations are resolved
   against the real evidence corpus and artifacts (RFC 6901 pointers) rather
   than taken on trust, with bounded repair hints when a pointer misses.

Acceptance is worst-tier-wins (:class:`SeverityPolicy`), never a weighted mean:
averaging lets a long tail of grounded claims dilute a single fabrication.

Usage::

    from llm_client.claim_verification import (
        SeverityPolicy, verify_report, load_severity_rubric,
    )

    policy = SeverityPolicy.default()
    result = verify_report(
        report,
        evidence_ids={"evi_a", "evi_b"},
        artifacts={"bayesian": bayesian_json},
        policy=policy,
    )
    result.status          # "accepted" | "repairable" | "blocked"
    result.citation_errors # deterministic provenance failures, if any
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client.rubric_registry import Rubric, load_rubric

logger = logging.getLogger(__name__)

SEVERITY_RUBRIC_NAME = "claim_verification_severity"
SEVERITY_DIMENSION = "claim_severity"

_PACKAGE_RUBRICS_DIR = Path(__file__).resolve().parent.parent / "rubrics"

Outcome = Literal["accepted", "repairable", "blocked"]

# RFC 6901: a pointer is "" or a sequence of "/" prefixed reference tokens.
_JSON_POINTER_PATTERN = r"^(?:/(?:[^~/]|~[01])*)*$"


def load_severity_rubric() -> Rubric:
    """Load the shared graduated-severity rubric.

    Returns:
        The ``claim_verification_severity`` :class:`~llm_client.rubric_registry.Rubric`.
    """
    return load_rubric(str(_PACKAGE_RUBRICS_DIR / f"{SEVERITY_RUBRIC_NAME}.yaml"))


# ---------------------------------------------------------------------------
# Judge-facing models
# ---------------------------------------------------------------------------


class ArtifactLocator(BaseModel):
    """One exact RFC 6901 JSON Pointer into a named supplied artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(
        min_length=1,
        description="Name of the supplied artifact this pointer indexes into.",
    )
    json_pointer: str = Field(
        pattern=_JSON_POINTER_PATTERN,
        description=(
            "Exact RFC 6901 JSON Pointer to the value in that artifact which "
            "supports the claim, e.g. /hypotheses/0/posterior."
        ),
    )


class ClaimSupport(BaseModel):
    """One provenance record backing a specific part of a claim.

    A claim may carry several of these. That is the point: a claim that fuses a
    directly observed premise with a computed conclusion has two different kinds
    of support, and recording only one of them makes the other half look
    unsupported no matter which is chosen.
    """

    model_config = ConfigDict(extra="forbid")

    basis: str = Field(
        min_length=1,
        description=(
            "Caller-declared support regime for this part of the claim, e.g. "
            "'source_evidence' or 'computed_artifact'."
        ),
    )
    covers: str = Field(
        min_length=1,
        description=(
            "The part of the claim this record supports. Quote the sub-span "
            "when the claim has parts resting on different kinds of support."
        ),
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Exact IDs from the supplied evidence corpus. Never invent one.",
    )
    artifact_locators: list[ArtifactLocator] = Field(
        default_factory=list,
        description="Exact locators into supplied artifacts backing this part.",
    )

    @model_validator(mode="after")
    def _no_duplicate_citations(self) -> ClaimSupport:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("claim support duplicates evidence IDs")
        identities = [(loc.artifact_ref, loc.json_pointer) for loc in self.artifact_locators]
        if len(identities) != len(set(identities)):
            raise ValueError("claim support duplicates artifact locators")
        if not self.evidence_ids and not self.artifact_locators:
            raise ValueError("claim support must cite evidence IDs or artifact locators")
        return self


class VerifiedClaim(BaseModel):
    """One atomic claim with its graduated severity judgment and provenance."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    claim_text: str = Field(min_length=1)
    severity: str = Field(
        description=(
            "Exactly one severity tier name from the claim_verification_severity "
            "rubric. Choose the least severe tier that honestly applies."
        )
    )
    supports: list[ClaimSupport] = Field(
        default_factory=list,
        description=(
            "One entry per part of the claim that rests on a distinct kind of "
            "support. Required unless the claim is fabricated."
        ),
    )
    reasoning: str = Field(
        min_length=12,
        description="Why this tier, grounded in the cited evidence.",
    )


class ClaimVerificationReport(BaseModel):
    """A judge's graduated-severity verdict over one decomposed text."""

    model_config = ConfigDict(extra="forbid")

    claims: list[VerifiedClaim] = Field(min_length=1)
    overall_assessment: str = Field(min_length=20)

    @model_validator(mode="after")
    def _unique_claim_ids(self) -> ClaimVerificationReport:
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim verification report duplicates claim IDs")
        return self


# ---------------------------------------------------------------------------
# Severity policy — worst-tier-wins gating
# ---------------------------------------------------------------------------


class SeverityPolicy(BaseModel):
    """Maps severity tiers to accept / repair / block outcomes.

    The gate is worst-tier-wins. A report is ``accepted`` only when every claim
    is acceptable, ``blocked`` when any claim is blocking, and ``repairable``
    otherwise — the middle state that a binary judge cannot express, covering
    claims whose *content* is right but whose provenance record is not.
    """

    model_config = ConfigDict(extra="forbid")

    rubric: Rubric
    accept_at_or_above: float = Field(
        default=0.8, description="Tier score at or above which a claim is accepted."
    )
    repair_at_or_above: float = Field(
        default=0.4,
        description=(
            "Tier score at or above which a claim is repairable rather than "
            "blocking. Below this, the claim blocks."
        ),
    )

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> SeverityPolicy:
        if self.repair_at_or_above > self.accept_at_or_above:
            raise ValueError("repair threshold cannot exceed accept threshold")
        if self.rubric.get_dimension(SEVERITY_DIMENSION) is None:
            raise ValueError(
                f"severity rubric must define a {SEVERITY_DIMENSION!r} dimension"
            )
        return self

    @classmethod
    def default(cls) -> SeverityPolicy:
        """Policy over the shared rubric with default thresholds."""
        return cls(rubric=load_severity_rubric())

    @property
    def tier_names(self) -> list[str]:
        """Tier names in rubric order, most to least severe-tolerant."""
        dim = self.rubric.get_dimension(SEVERITY_DIMENSION)
        assert dim is not None  # guaranteed by _thresholds_ordered
        return [c.name for c in dim.categories]

    def tier_score(self, severity: str) -> float:
        """Score for a tier name.

        Raises:
            ValueError: If the tier is not defined by the rubric. Fail loud —
                an unknown tier must never be silently treated as acceptable.
        """
        dim = self.rubric.get_dimension(SEVERITY_DIMENSION)
        assert dim is not None
        cat = dim.category_by_name(severity)
        if cat is None:
            raise ValueError(
                f"Unknown severity tier {severity!r}. Valid: {self.tier_names}"
            )
        return cat.score

    def outcome(self, severity: str) -> Outcome:
        """Outcome for a single claim's tier."""
        score = self.tier_score(severity)
        if score >= self.accept_at_or_above:
            return "accepted"
        if score >= self.repair_at_or_above:
            return "repairable"
        return "blocked"

    def status(self, severities: list[str]) -> Outcome:
        """Worst-tier-wins status over many claims.

        An empty claim list is a programming error, not an acceptance.
        """
        if not severities:
            raise ValueError("cannot compute status over zero claims")
        outcomes = {self.outcome(s) for s in severities}
        if "blocked" in outcomes:
            return "blocked"
        if "repairable" in outcomes:
            return "repairable"
        return "accepted"


# ---------------------------------------------------------------------------
# Deterministic post-judgment verification
# ---------------------------------------------------------------------------


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer against a document.

    Args:
        document: Parsed JSON-like structure.
        pointer: RFC 6901 pointer. ``""`` resolves to the whole document.

    Returns:
        The referenced value.

    Raises:
        ValueError: If the pointer does not resolve. The message names the
            pointer; callers add repair hints via :func:`pointer_repair_hints`.
    """
    if pointer == "":
        return document
    current = document
    for raw in pointer.removeprefix("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ValueError(f"pointer does not resolve: {pointer}")
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError(f"pointer does not resolve: {pointer}")
    return current


def pointer_repair_hints(document: Any, pointer: str, *, limit: int = 20) -> list[str]:
    """Enumerate valid pointers whose final token matches the requested one.

    A judge that misses a pointer has usually named the right field at the wrong
    depth, so exact same-field candidates make the miss cheaply repairable
    instead of merely rejected.
    """
    tokens = pointer.removeprefix("/").split("/")
    requested_leaf = tokens[-1] if tokens else ""
    candidates: list[str] = []

    def walk(value: Any, path: list[str]) -> None:
        if len(candidates) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                walk(child, [*path, escaped])
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, [*path, str(index)])
            return
        if path and path[-1] == requested_leaf:
            candidates.append("/" + "/".join(path))

    walk(document, [])
    return candidates


class CitationError(BaseModel):
    """One deterministic provenance failure found in a judge's output."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    kind: Literal["unknown_evidence_id", "unknown_artifact", "unresolved_pointer"]
    detail: str
    repair_hints: list[str] = Field(default_factory=list)


class ClaimVerificationResult(BaseModel):
    """A verified report: judge verdict plus deterministic citation checks."""

    model_config = ConfigDict(extra="forbid")

    report: ClaimVerificationReport
    status: Outcome
    outcomes: dict[str, Outcome]
    citation_errors: list[CitationError] = Field(default_factory=list)

    @property
    def repairable_claims(self) -> list[str]:
        """Claim IDs whose content stands but whose provenance needs repair."""
        return [cid for cid, o in self.outcomes.items() if o == "repairable"]

    @property
    def blocking_claims(self) -> list[str]:
        """Claim IDs that block acceptance."""
        return [cid for cid, o in self.outcomes.items() if o == "blocked"]


def verify_report(
    report: ClaimVerificationReport,
    *,
    evidence_ids: set[str],
    artifacts: dict[str, Any],
    policy: SeverityPolicy,
    citation_errors_block: bool = True,
) -> ClaimVerificationResult:
    """Check a judge's report against the real evidence corpus and artifacts.

    The judge's severity tiers set the graduated outcome; this function
    independently confirms every citation actually exists and resolves. A judge
    that cites a plausible-looking but absent evidence ID is caught here, not
    trusted.

    Args:
        report: The judge's output.
        evidence_ids: Closed set of valid evidence IDs.
        artifacts: Supplied artifacts by name, for locator resolution.
        policy: Severity policy supplying the gate.
        citation_errors_block: When true (default), any citation error forces a
            blocked status regardless of the judged tiers.

    Returns:
        :class:`ClaimVerificationResult` with the gated status and any errors.
    """
    errors: list[CitationError] = []

    for claim in report.claims:
        for support in claim.supports:
            for eid in support.evidence_ids:
                if eid not in evidence_ids:
                    errors.append(
                        CitationError(
                            claim_id=claim.claim_id,
                            kind="unknown_evidence_id",
                            detail=f"evidence ID not in the supplied corpus: {eid}",
                        )
                    )
            for locator in support.artifact_locators:
                artifact = artifacts.get(locator.artifact_ref)
                if artifact is None:
                    errors.append(
                        CitationError(
                            claim_id=claim.claim_id,
                            kind="unknown_artifact",
                            detail=(
                                "locator names an unavailable artifact: "
                                f"{locator.artifact_ref}"
                            ),
                            repair_hints=sorted(artifacts),
                        )
                    )
                    continue
                try:
                    resolve_json_pointer(artifact, locator.json_pointer)
                except ValueError as exc:
                    errors.append(
                        CitationError(
                            claim_id=claim.claim_id,
                            kind="unresolved_pointer",
                            detail=f"{locator.artifact_ref}: {exc}",
                            repair_hints=pointer_repair_hints(
                                artifact, locator.json_pointer
                            ),
                        )
                    )

    outcomes = {c.claim_id: policy.outcome(c.severity) for c in report.claims}
    status = policy.status([c.severity for c in report.claims])
    if errors and citation_errors_block:
        status = "blocked"

    if errors:
        logger.warning(
            "claim verification found %d citation error(s) across %d claim(s)",
            len(errors),
            len({e.claim_id for e in errors}),
        )

    return ClaimVerificationResult(
        report=report,
        status=status,
        outcomes=outcomes,
        citation_errors=errors,
    )


# ---------------------------------------------------------------------------
# Judge entrypoint
# ---------------------------------------------------------------------------


class SupportBasis(BaseModel):
    """One caller-declared support regime offered to the judge."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


DEFAULT_SUPPORT_BASES: tuple[SupportBasis, ...] = (
    SupportBasis(
        name="source_evidence",
        description=(
            "A proposition about what occurred, directly supported by one or "
            "more accepted source observations. Cite their evidence IDs."
        ),
    ),
    SupportBasis(
        name="computed_artifact",
        description=(
            "A result this run computed — a posterior, likelihood, rank, "
            "threshold, gate outcome, or matrix cell. Cite the exact artifact "
            "locator. Do not reject it merely because no source states the "
            "computation."
        ),
    ),
)

CLAIM_VERIFICATION_PROMPT_REF = "shared.claim_verification.graduated_severity@1"
"""Explicit shared prompt asset identity for the judge (ADR 0011)."""


def build_claim_verification_messages(
    claims: list[dict[str, Any]],
    *,
    evidence: Any,
    artifacts: dict[str, Any],
    policy: SeverityPolicy,
    support_bases: tuple[SupportBasis, ...] = DEFAULT_SUPPORT_BASES,
) -> list[dict[str, str]]:
    """Render the shared claim-verification judge prompt.

    Separated from :func:`verify_claims` so callers can inspect or hash the
    exact prompt without making a model call.
    """
    import json

    from llm_client.prompts import render_prompt

    dim = policy.rubric.get_dimension(SEVERITY_DIMENSION)
    assert dim is not None
    return render_prompt(
        prompt_ref=CLAIM_VERIFICATION_PROMPT_REF,
        severity_tiers=[
            {"name": c.name, "description": " ".join(c.description.split())}
            for c in dim.categories
        ],
        support_bases=[b.model_dump() for b in support_bases],
        claims_json=json.dumps(claims, indent=2),
        evidence_json=json.dumps(evidence, indent=2),
        artifacts_json=json.dumps(artifacts, indent=2),
    )


def verify_claims(
    claims: list[dict[str, Any]],
    *,
    evidence: Any,
    evidence_ids: set[str],
    artifacts: dict[str, Any],
    task: str,
    trace_id: str,
    max_budget: float,
    model: str,
    policy: SeverityPolicy | None = None,
    support_bases: tuple[SupportBasis, ...] = DEFAULT_SUPPORT_BASES,
    **call_kwargs: Any,
) -> ClaimVerificationResult:
    """Judge atomic claims on a graduated severity scale, then verify citations.

    Args:
        claims: Atomic claims to judge; each needs at least ``claim_id`` and
            ``claim_text``. Decomposition is the caller's responsibility.
        evidence: Evidence corpus shown to the judge.
        evidence_ids: Closed set of valid evidence IDs, checked deterministically.
        artifacts: Supplied artifacts by name, shown to the judge and used to
            resolve its locators.
        task: Required observability task tag.
        trace_id: Required observability trace ID.
        max_budget: Required spend ceiling for the call.
        model: Judge model.
        policy: Severity policy; defaults to the shared rubric and thresholds.
        support_bases: Support regimes offered to the judge.
        **call_kwargs: Passed through to ``call_llm_structured``.

    Returns:
        :class:`ClaimVerificationResult` with the gated status.
    """
    from llm_client.claim_verification_policy import (
        assert_sanctioned_claim_verification,
    )
    from llm_client.core.client import call_llm_structured

    resolved_policy = policy or SeverityPolicy.default()
    messages = build_claim_verification_messages(
        claims,
        evidence=evidence,
        artifacts=artifacts,
        policy=resolved_policy,
        support_bases=support_bases,
    )
    response_model = build_report_model(
        artifact_refs=set(artifacts),
        bases={b.name for b in support_bases},
        severities=resolved_policy.tier_names,
    )
    # Fail closed before spending anything: a caller that has swapped in its own
    # report model is running an unreviewed judge, not this one.
    assert_sanctioned_claim_verification(response_model, task=task)
    report, _result = call_llm_structured(
        model,
        messages,
        response_model=response_model,
        task=task,
        trace_id=trace_id,
        max_budget=max_budget,
        **call_kwargs,
    )
    return verify_report(
        report,
        evidence_ids=evidence_ids,
        artifacts=artifacts,
        policy=resolved_policy,
    )


# ---------------------------------------------------------------------------
# Constrained response models
# ---------------------------------------------------------------------------


def build_report_model(
    *,
    artifact_refs: set[str],
    bases: set[str],
    severities: list[str],
) -> type[ClaimVerificationReport]:
    """Build a response model whose vocabularies are closed at the schema level.

    Leaving ``artifact_ref``, ``basis`` and ``severity`` as free-form strings
    invites a judge to write a prose description where an identifier belongs —
    observed in practice, where a locator's ``artifact_ref`` came back as
    "Bayes posterior and diagnostic matrix entries for hypothesis h1" instead of
    "bayesian". Pinning each to a literal set makes that unrepresentable rather
    than merely detectable after the fact.

    Args:
        artifact_refs: Exact names of the supplied artifacts. When empty, claims
            cannot carry locators at all.
        bases: Exact support-regime names offered to the judge.
        severities: Exact tier names from the severity rubric.

    Returns:
        A :class:`ClaimVerificationReport` subclass with closed vocabularies.
    """
    from pydantic import create_model

    if not bases:
        raise ValueError("at least one support basis is required")
    if not severities:
        raise ValueError("at least one severity tier is required")

    basis_type = Literal[tuple(sorted(bases))]  # type: ignore[valid-type]
    severity_type = Literal[tuple(severities)]  # type: ignore[valid-type]

    support_fields: dict[str, Any] = {"basis": (basis_type, Field(...))}
    if artifact_refs:
        ref_type = Literal[tuple(sorted(artifact_refs))]  # type: ignore[valid-type]
        locator_model = create_model(
            "ConstrainedArtifactLocator",
            __base__=ArtifactLocator,
            artifact_ref=(
                ref_type,
                Field(description="Exact name of one supplied artifact."),
            ),
        )
        support_fields["artifact_locators"] = (
            list[locator_model],  # type: ignore[valid-type]
            Field(default_factory=list),
        )
    else:
        support_fields["artifact_locators"] = (
            list[ArtifactLocator],
            Field(default_factory=list, max_length=0),
        )

    support_model = create_model(
        "ConstrainedClaimSupport", __base__=ClaimSupport, **support_fields
    )
    claim_model = create_model(
        "ConstrainedVerifiedClaim",
        __base__=VerifiedClaim,
        severity=(
            severity_type,
            Field(description="Exactly one severity tier name."),
        ),
        supports=(list[support_model], Field(default_factory=list)),  # type: ignore[valid-type]
    )
    return create_model(
        "ConstrainedClaimVerificationReport",
        __base__=ClaimVerificationReport,
        claims=(list[claim_model], Field(min_length=1)),  # type: ignore[valid-type]
    )
