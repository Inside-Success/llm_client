"""Exact-key route certification registry and corruption controls."""

from datetime import UTC, datetime, timedelta
import json

import pytest

from llm_client.route_certification import (
    RouteCertificationObservation,
    RouteCertificationStore,
)


def _observation(**changes: object) -> RouteCertificationObservation:
    values: dict[str, object] = {
        "requested_model": "openrouter/x-ai/grok-4.5",
        "resolved_model": "openrouter/x-ai/grok-4.5",
        "upstream_provider_endpoint": "xai",
        "execution_mode": "native_json_schema",
        "schema_class": "plan0141-coreference-proposal-v1",
        "schema_sha256": "a" * 64,
        "outcome": "parseable",
        "failure_stage": "none",
        "logical_call_id": "call-1",
        "trace_id": "trace-1",
        "observed_at": datetime(2026, 7, 16, tzinfo=UTC),
        "llm_client_revision": "revision-1",
        "selected_attempt_receipt_digest": "b" * 64,
        "evidence_ref": "artifact://trace-1",
    }
    values.update(changes)
    return RouteCertificationObservation.build(**values)


def test_store_preserves_certification_and_latest_health(tmp_path) -> None:
    """A later timeout remains visible without erasing prior transport proof."""

    store = RouteCertificationStore(tmp_path)
    passed = _observation()
    timeout = _observation(
        outcome="timeout",
        failure_stage="provider_runtime",
        logical_call_id="call-2",
        trace_id="trace-2",
        observed_at=passed.observed_at + timedelta(hours=1),
        selected_attempt_receipt_digest=None,
        evidence_ref="artifact://trace-2",
    )
    store.append(passed)
    store.append(timeout)

    view = store.query(
        resolved_model=passed.resolved_model,
        upstream_provider_endpoint=passed.upstream_provider_endpoint,
        execution_mode=passed.execution_mode,
        schema_class=passed.schema_class,
        schema_sha256=passed.schema_sha256,
    )
    assert view is not None
    assert view.transport_certified is True
    assert view.certification_observation_id == passed.observation_id
    assert view.latest_outcome == "timeout"
    assert view.observation_count == 2


def test_unknown_endpoint_never_certifies_named_route(tmp_path) -> None:
    """Parseable output without actual endpoint identity stays observational."""

    store = RouteCertificationStore(tmp_path)
    unknown = _observation(upstream_provider_endpoint=None)
    store.append(unknown)
    view = store.query(
        resolved_model=unknown.resolved_model,
        upstream_provider_endpoint=None,
        execution_mode=unknown.execution_mode,
        schema_class=unknown.schema_class,
        schema_sha256=unknown.schema_sha256,
    )
    assert view is not None
    assert view.transport_certified is False


def test_schema_digest_and_endpoint_are_exact_query_keys(tmp_path) -> None:
    """Certification cannot leak across endpoint or schema changes."""

    store = RouteCertificationStore(tmp_path)
    passed = _observation()
    store.append(passed)
    assert store.query(
        resolved_model=passed.resolved_model,
        upstream_provider_endpoint="other-provider",
        execution_mode=passed.execution_mode,
        schema_class=passed.schema_class,
        schema_sha256=passed.schema_sha256,
    ) is None
    assert store.query(
        resolved_model=passed.resolved_model,
        upstream_provider_endpoint=passed.upstream_provider_endpoint,
        execution_mode=passed.execution_mode,
        schema_class=passed.schema_class,
        schema_sha256="c" * 64,
    ) is None


def test_corrupt_persisted_record_fails_replay(tmp_path) -> None:
    """A self-inconsistent persisted observation cannot enter a query view."""

    store = RouteCertificationStore(tmp_path)
    passed = _observation()
    path = store.append(passed)
    payload = passed.model_dump(mode="json") | {"outcome": "invalid_output"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="route observation digest mismatch"):
        store.observations()


def test_success_and_failure_stage_must_agree() -> None:
    """Certification records cannot claim success while naming a failure stage."""

    with pytest.raises(ValueError, match="outcome and failure stage disagree"):
        _observation(failure_stage="schema_transport")


def test_failure_outcome_must_use_its_owned_stage() -> None:
    """A capacity rejection cannot be mislabeled as local validation."""

    with pytest.raises(ValueError, match="wrong stage"):
        _observation(
            outcome="capacity_rejected",
            failure_stage="local_validation",
            selected_attempt_receipt_digest=None,
        )
