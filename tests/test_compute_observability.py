"""Contract tests for provider-neutral compute observability."""

import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from llm_client import io_log
from llm_client.observability.compute_observability import (
    ComputeObservabilityError,
    OutcomeReceiptV1,
    QuotaWindow,
    TaskAttemptReceiptV1,
    UsageSnapshotV1,
    parse_ccusage_daily_json,
    parse_codexbar_usage_json,
    persist_usage_snapshot,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _temporary_observability_db(tmp_path):
    old_path = io_log._db_path
    io_log.configure(enabled=True, db_path=tmp_path / "observability.db")
    try:
        yield
    finally:
        io_log.close()
        io_log._db_path = old_path


def _snapshot(raw: dict[str, object]) -> UsageSnapshotV1:
    raw_json = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return UsageSnapshotV1(
        snapshot_id="snapshot-1",
        source_name="fixture",
        source_version="1",
        observed_at=_now(),
        machine_id="machine-a",
        provider="codex",
        account_fingerprint="unknown",
        billing_mode="subscription",
        raw_record_sha256=hashlib.sha256(raw_json.encode()).hexdigest(),
    )


def test_usage_snapshot_preserves_quota_and_separates_cost_kinds() -> None:
    snapshot = UsageSnapshotV1(
        snapshot_id="ccusage:machine-a:account-a:2026-09-10T12:00:00Z",
        source_name="ccusage",
        source_version="fixture-1",
        observed_at=_now(),
        machine_id="machine-a",
        provider="claude",
        model="claude-sonnet",
        account_fingerprint="a" * 64,
        billing_mode="subscription",
        quota_windows=(QuotaWindow(name="weekly", used_percent=50, reset_at=_now()),),
        input_tokens=100,
        cached_input_tokens=40,
        output_tokens=20,
        reasoning_tokens=None,
        api_equivalent_cost_usd=1.25,
        actual_marginal_cost_usd=None,
        actual_cost_source=None,
        raw_record_sha256="b" * 64,
    )

    assert snapshot.quota_windows[0].used_percent == 50
    assert snapshot.api_equivalent_cost_usd == 1.25
    assert snapshot.actual_marginal_cost_usd is None


def test_task_attempt_rejects_end_before_start() -> None:
    start = _now()
    with pytest.raises(ValidationError, match="ended_at cannot precede started_at"):
        TaskAttemptReceiptV1(
            task_id="task-1",
            attempt_id="attempt-1",
            provider="codex",
            account_fingerprint="unknown",
            machine_id="machine-a",
            billing_mode="subscription",
            started_at=start,
            ended_at=start.replace(year=start.year - 1),
        )


def test_unknown_account_is_allowed_but_plaintext_identity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="account_fingerprint"):
        UsageSnapshotV1(
            snapshot_id="snapshot-1",
            source_name="provider",
            source_version="fixture-1",
            observed_at=_now(),
            machine_id="machine-a",
            provider="codex",
            account_fingerprint="person@example.com",
            billing_mode="api",
            raw_record_sha256="c" * 64,
        )


def test_outcome_receipt_does_not_equate_call_success_with_shipped_value() -> None:
    outcome = OutcomeReceiptV1(
        task_id="task-1",
        attempt_id="attempt-1",
        coordinator_decision="accepted",
        tests_status="pass",
        ci_status="pass",
        static_analysis_status="pass",
        merged=True,
        weighted_shipped_value=3.0,
        critical_path_seconds=120,
        recorded_at=_now(),
    )

    assert outcome.coordinator_decision == "accepted"
    assert outcome.merged is True
    assert outcome.weighted_shipped_value == 3.0


def test_usage_snapshot_persistence_is_idempotent() -> None:
    raw = {"provider": "codex", "usage": {"input": 10, "output": 2}}
    snapshot = _snapshot(raw)

    assert persist_usage_snapshot(snapshot, sanitized_raw_record=raw) is True
    assert persist_usage_snapshot(snapshot, sanitized_raw_record=raw) is False


def test_usage_snapshot_persistence_rejects_credential_fields() -> None:
    raw = {"provider": "codex", "api_key": "not-stored"}
    snapshot = _snapshot({"provider": "codex"})

    with pytest.raises(ComputeObservabilityError, match="credential-bearing"):
        persist_usage_snapshot(snapshot, sanitized_raw_record=raw)

    with pytest.raises(ComputeObservabilityError, match="credential-bearing"):
        persist_usage_snapshot(snapshot, sanitized_raw_record={"accountEmail": "redact@example.com"})


def test_ccusage_daily_json_normalizes_model_breakdowns_without_repricing() -> None:
    snapshots = parse_ccusage_daily_json(
        {
            "daily": [
                {
                    "agent": "codex",
                    "period": "2026-09-10",
                    "modelBreakdowns": [
                        {
                            "modelName": "gpt-5.6-luna",
                            "inputTokens": 10,
                            "cacheReadTokens": 4,
                            "outputTokens": 3,
                            "cost": 0.25,
                        }
                    ],
                }
            ]
        },
        machine_id="machine-a",
        account_fingerprint="unknown",
        billing_mode="subscription",
        source_version="20.0.20",
    )

    assert len(snapshots) == 1
    assert snapshots[0].model == "gpt-5.6-luna"
    assert snapshots[0].cached_input_tokens == 4
    assert snapshots[0].api_equivalent_cost_usd == 0.25
    assert snapshots[0].actual_marginal_cost_usd is None


def test_codexbar_usage_normalizes_quota_windows_without_storing_identity() -> None:
    snapshots = parse_codexbar_usage_json(
        [
            {
                "provider": "codex",
                "source": "codex-cli",
                "usage": {
                    "updatedAt": "2026-09-10T07:36:55Z",
                    "secondary": {
                        "usedPercent": 21,
                        "windowMinutes": 10080,
                        "resetsAt": "2026-09-17T04:35:04Z",
                    },
                    "identity": {"providerID": "codex", "loginMethod": "pro"},
                },
            }
        ],
        machine_id="machine-a",
        account_fingerprint="d" * 64,
        source_version="0.56.8",
    )

    assert len(snapshots) == 1
    assert snapshots[0].quota_windows[0].used_percent == 21
    assert snapshots[0].quota_windows[0].reset_at is not None
    assert snapshots[0].account_fingerprint == "d" * 64
    assert snapshots[0].actual_marginal_cost_usd is None
