"""Tests for standalone adversarial-review schemas and profiles."""

from __future__ import annotations

import pytest

from llm_client.workflow.adversarial_review import (
    AdversarialReview,
    ReviewAnnotation,
    ReviewProfile,
    adversarial_review_response_schema,
    adversarial_review_schema,
    build_review_prompt,
    get_review_profile,
    list_review_profiles,
    normalize_adversarial_review_response,
    register_review_profile,
    render_quality_optimal_sections,
    resolve_review_schema_version,
)
from llm_client.workflow.duet import CorrectnessFinding


def test_builtin_profiles_registered() -> None:
    assert "generic" in list_review_profiles()
    assert "quality_optimal_whitepaper" in list_review_profiles()
    assert not get_review_profile("generic").requires_schema_v2
    assert get_review_profile("quality_optimal_whitepaper").requires_schema_v2


def test_registry_rejects_duplicate_profile() -> None:
    with pytest.raises(ValueError):
        register_review_profile(ReviewProfile(name="generic"))


def test_registry_unknown_profile_raises_clear_error() -> None:
    with pytest.raises(KeyError, match="Unknown review profile"):
        get_review_profile("missing")


def test_review_annotation_optimum_gap_requires_link_and_validity_loss() -> None:
    with pytest.raises(ValueError, match="linked_finding_index"):
        ReviewAnnotation(
            annotation_id="a1",
            kind="optimum_gap",
            claim="Add causal check",
            validity_loss_without_change="Current analysis confounds X and Y.",
        )
    with pytest.raises(ValueError, match="validity_loss_without_change"):
        ReviewAnnotation(
            annotation_id="a1",
            kind="optimum_gap",
            claim="Add causal check",
            linked_finding_index=0,
        )


def test_review_annotation_spurious_requires_rejection_reason() -> None:
    with pytest.raises(ValueError, match="why_rejected_or_uncertain"):
        ReviewAnnotation(
            annotation_id="s1",
            kind="spurious",
            claim="Add a table because papers have tables",
        )


def test_schema_v1_preserves_original_strict_shape() -> None:
    schema = adversarial_review_schema("1")
    instance = schema(artifact_label="x", verdict="pass", summary="ok")
    assert "profile_annotations" not in instance.model_dump()
    with pytest.raises(Exception):
        schema(
            artifact_label="x",
            verdict="pass",
            summary="ok",
            profile_annotations=[],
        )


def test_schema_v2_accepts_profile_annotations() -> None:
    schema = adversarial_review_schema("2")
    instance = schema(
        artifact_label="x",
        verdict="concerns",
        summary="needs work",
        correctness_findings=[
            CorrectnessFinding(
                file_path="paper.md",
                line=12,
                claim="The design omits the validation signal.",
                severity="high",
            )
        ],
        profile_annotations=[
            ReviewAnnotation(
                annotation_id="og1",
                kind="optimum_gap",
                claim="Add validation signal",
                linked_finding_index=0,
                validity_loss_without_change="The paper cannot detect false positives.",
            )
        ],
    )
    assert isinstance(instance, AdversarialReview)
    assert instance.profile_annotations[0].kind == "optimum_gap"


def test_response_schema_v2_accepts_repairable_annotation() -> None:
    schema = adversarial_review_response_schema("2")
    response = schema(
        artifact_label="x",
        verdict="concerns",
        summary="needs discussion",
        profile_annotations=[
            {
                "annotation_id": "u1",
                "kind": "uncertain",
                "claim": "Maybe add adjudication details",
            }
        ],
    )

    normalized = normalize_adversarial_review_response(response)

    assert isinstance(normalized, AdversarialReview)
    assert normalized.profile_annotations[0].kind == "uncertain"
    assert "omitted why_rejected_or_uncertain" in normalized.profile_annotations[0].why_rejected_or_uncertain


def test_invalid_optimum_gap_response_is_routed_to_discussion() -> None:
    normalized = normalize_adversarial_review_response(
        {
            "artifact_label": "x",
            "verdict": "concerns",
            "summary": "bad optimum gap",
            "profile_annotations": [
                {
                    "annotation_id": "og1",
                    "kind": "optimum_gap",
                    "claim": "Add a component",
                }
            ],
        }
    )

    assert isinstance(normalized, AdversarialReview)
    assert normalized.profile_annotations[0].kind == "uncertain"
    assert "Invalid optimum_gap" in normalized.profile_annotations[0].why_rejected_or_uncertain


def test_quality_profile_requires_schema_v2() -> None:
    generic = get_review_profile("generic")
    quality = get_review_profile("quality_optimal_whitepaper")
    assert resolve_review_schema_version(generic, "auto") == "1"
    assert resolve_review_schema_version(quality, "auto") == "2"
    with pytest.raises(ValueError, match="requires review schema version 2"):
        resolve_review_schema_version(quality, "1")


def test_quality_profile_adds_prompt_contract() -> None:
    schema = adversarial_review_schema("2")
    messages = build_review_prompt(
        artifact_label="methodology.md",
        artifact_body="paper body",
        context_body="north-star architecture",
        response_schema=schema,
        profile=get_review_profile("quality_optimal_whitepaper"),
    )
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "compute cost treated as unconstrained" in system
    assert "profile_annotations kind=optimum_gap" in user
    assert "methodology.md" in user


def test_normalize_rejects_boolean_optimum_gap_link() -> None:
    normalized = normalize_adversarial_review_response(
        {
            "artifact_label": "paper",
            "verdict": "concerns",
            "summary": "summary",
            "correctness_findings": [
                {"file_path": "paper.md", "line": 1, "claim": "defect", "severity": "high"}
            ],
            "contract_violations": [],
            "nits": [],
            "unverified_claims": [],
            "scope_drift_findings": [],
            "profile_annotations": [
                {
                    "annotation_id": "og-bool",
                    "kind": "optimum_gap",
                    "claim": "bad bool link",
                    "linked_finding_index": True,
                    "validity_loss_without_change": "loss",
                }
            ],
        }
    )

    assert isinstance(normalized, AdversarialReview)
    assert normalized.profile_annotations[0].kind == "uncertain"
    assert normalized.profile_annotations[0].linked_finding_index is None


def test_render_quality_optimal_sections_from_canonical_json() -> None:
    review = AdversarialReview(
        artifact_label="methodology.md",
        verdict="concerns",
        summary="summary",
        correctness_findings=[
            CorrectnessFinding(
                file_path="methodology.md",
                line=10,
                claim="The estimator cannot identify the target quantity.",
                severity="high",
            )
        ],
        profile_annotations=[
            ReviewAnnotation(
                annotation_id="og1",
                kind="optimum_gap",
                claim="Add identification proof",
                linked_finding_index=0,
                validity_loss_without_change="The paper cannot distinguish estimand from estimator.",
            ),
            ReviewAnnotation(
                annotation_id="sp1",
                kind="spurious",
                claim="Add a benchmark table",
                why_rejected_or_uncertain="No validity loss follows from its absence.",
            ),
        ],
    )
    rendered = render_quality_optimal_sections(review)
    assert "[DEFECT]" in rendered
    assert "[OPTIMUM-GAP]" in rendered
    assert "[SPURIOUS]" in rendered
    assert "What is wrong without it" in rendered
    assert "No validity loss" in rendered


def test_render_quality_optimal_sections_routes_duplicate_optimum_gap_to_uncertain() -> None:
    review = AdversarialReview(
        artifact_label="methodology.md",
        verdict="concerns",
        summary="summary",
        correctness_findings=[
            CorrectnessFinding(
                file_path="methodology.md",
                line=10,
                claim="The estimator cannot identify the target quantity.",
                severity="high",
            )
        ],
        profile_annotations=[
            ReviewAnnotation(
                annotation_id="og1",
                kind="optimum_gap",
                claim="Add identification proof",
                linked_finding_index=0,
                validity_loss_without_change="The paper cannot distinguish estimand from estimator.",
            ),
            ReviewAnnotation(
                annotation_id="og2",
                kind="optimum_gap",
                claim="Duplicate identification proof",
                linked_finding_index=0,
                validity_loss_without_change="Duplicate.",
            ),
        ],
    )

    rendered = render_quality_optimal_sections(review)

    assert rendered.count("What is wrong without it") == 1
    assert "duplicate optimum_gap linked_finding_index" in rendered
