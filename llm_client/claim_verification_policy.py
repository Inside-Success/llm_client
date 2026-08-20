"""Fail-closed policy for claim-verification judges.

A claim-verification judge decomposes a text into atomic claims and rules on
each against cited evidence. `llm_client.claim_verification` is the sanctioned
implementation. This module exists so a bespoke one-off judge cannot quietly
reappear alongside it, the way `model_execution_policy` keeps model routing from
drifting into per-project configuration.

Registration is explicit, and deliberately so.

    Automatic detection was investigated and rejected on measured evidence, not
    on taste. Three detectors were run over 6,267 distinct response schemas
    sampled from the shared observability database, scored against a task-tag
    proxy for "this call judges something":

        detector                      precision  recall
        response field names            0.30      0.08
        field names, recursing $defs    0.01      0.22
        structural (list-of-claims      0.02      0.81
          each with an enum verdict)

    Every variant is unusable. The name-based ones miss the judges this very
    module governs, because a judge nests its verdicts inside `claims` or
    `decisions` and its top-level fields are unremarkable. The structural one
    reaches useful recall only by flagging 4,361 of 6,267 schemas — roughly
    seventy percent of the fleet, including ordinary extraction models — so
    enforcing on it would coerce most of the ecosystem through a judging
    primitive it has no business using.

    A detector that cannot recognise the canonical case while flagging most of
    everything else is worse than no detector: it would produce confident,
    wrong enforcement. So callers declare, and the declaration is checked.

Usage::

    from llm_client.claim_verification_policy import (
        assert_sanctioned_claim_verification,
    )

    assert_sanctioned_claim_verification(MyReportModel, task="pt.central_claim_review")
"""

from __future__ import annotations

from typing import Any

from llm_client.core.errors import LLMConfigurationError

__all__ = [
    "SANCTIONED_CLAIM_VERIFICATION_MODELS",
    "assert_sanctioned_claim_verification",
    "is_sanctioned_claim_verification",
    "qualified_name",
]

# Exact fully-qualified response models permitted to perform claim verification.
# Adding an entry is a reviewed source change, not a project configuration
# option. Register a model here only when it is built from
# `llm_client.claim_verification` or is a documented, time-bounded exception with
# an owner; a new bespoke judge belongs in that module instead.
SANCTIONED_CLAIM_VERIFICATION_MODELS: frozenset[str] = frozenset(
    {
        # The shared primitive, and the constrained models built from it by
        # llm_client.claim_verification.build_report_model().
        "llm_client.claim_verification.ClaimVerificationReport",
        "llm_client.claim_verification.ConstrainedClaimVerificationReport",
        # process_tracing's terminal reviewer, migrated onto the shared severity
        # rubric and multi-support provenance. Its models subclass a shared
        # vocabulary rather than redefining one; see
        # pt/schemas.py::CentralClaimEntailment and
        # tests/test_central_claim_severity.py, which pins its tier names to the
        # rubric shipped by the llm_client revision that repo pins.
        "pt.schemas.CentralClaimEntailmentReview",
        "pt.schemas.CentralClaimEntailmentReviewForSynthesis",
        "pt.schemas.CentralClaimEntailmentReviewForMechanism",
    }
)


def qualified_name(response_model: type[Any]) -> str:
    """Fully-qualified name of a response model, ignoring runtime-generated suffixes.

    `create_model()` derives per-call subclasses whose names carry a binding
    suffix — ``...ForMechanismBoundEvidenceIds``. Those are the same sanctioned
    contract with a narrower vocabulary, so registration resolves through the
    class's ancestry rather than requiring every generated name to be listed.
    """
    module = getattr(response_model, "__module__", "") or ""
    name = getattr(response_model, "__qualname__", None) or getattr(
        response_model, "__name__", ""
    )
    return f"{module}.{name}" if module else str(name)


def is_sanctioned_claim_verification(response_model: type[Any]) -> bool:
    """Whether this model, or a model it derives from, is registered.

    Checking ancestry is what makes the registry usable with dynamically
    constrained models: `build_report_model()` returns a subclass of the
    registered report, and process_tracing binds its evidence-ID enum the same
    way. A project cannot escape the registry by subclassing, because a
    subclass of a sanctioned model still implements the sanctioned contract.
    """
    for candidate in getattr(response_model, "__mro__", (response_model,)):
        if qualified_name(candidate) in SANCTIONED_CLAIM_VERIFICATION_MODELS:
            return True
    return False


def assert_sanctioned_claim_verification(
    response_model: type[Any],
    *,
    task: str,
) -> None:
    """Fail closed when a declared claim-verification call is not registered.

    Args:
        response_model: The structured response model the judge will return.
        task: Observability task tag, echoed into the error so the offending
            call site is identifiable from the message alone.

    Raises:
        LLMConfigurationError: If the model is not registered. The message names
            the shared primitive rather than only reporting a violation, because
            the intended resolution is to use it, not to add an entry here.
    """
    if is_sanctioned_claim_verification(response_model):
        return
    raise LLMConfigurationError(
        f"unregistered claim-verification response model "
        f"{qualified_name(response_model)!r} for task {task!r}. "
        "Claim verification must go through llm_client.claim_verification "
        "(build_report_model / verify_claims), which supplies graduated "
        "severity, multi-support provenance, and deterministic citation "
        "checking. If this genuinely cannot use the shared primitive, register "
        "it in SANCTIONED_CLAIM_VERIFICATION_MODELS as a reviewed source change."
    )
