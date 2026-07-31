from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from llm_client import io_log
from llm_client.observability.call_receipts import LLMCallReceiptV1
from llm_client.observability.query import get_llm_call_receipts


def _close_legacy_test_db() -> None:
    connection = io_log._db_conn
    if connection is not None:
        connection.close()
        io_log._db_conn = None


def test_terminal_receipt_requires_timing_or_explicit_gap() -> None:
    with pytest.raises(ValidationError, match="latency_s"):
        LLMCallReceiptV1(
            receipt_id="receipt-1",
            runtime="hermes",
            trace_id="trace-1",
            status="succeeded",
        )

    receipt = LLMCallReceiptV1(
        receipt_id="receipt-1",
        runtime="hermes",
        trace_id="trace-1",
        status="succeeded",
        unavailable_fields={"latency_s": "Hermes event did not expose per-call timing."},
    )
    assert receipt.latency_s is None


def test_query_projects_existing_terminal_row_without_copying_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("LLM_CLIENT_LOG_ENABLED", "1")
    _close_legacy_test_db()
    monkeypatch.setattr(io_log, "_db_path", tmp_path / "receipts.db")
    monkeypatch.setattr(io_log, "_db_conn", None)
    logical_call_id = "receipt-logical-1"
    trace_id = "receipt-trace-1"
    io_log._write_call_to_db(
        timestamp=datetime.now(timezone.utc).isoformat(),
        model="openrouter/example/model",
        messages=[{"role": "user", "content": "private prompt"}],
        response="private response",
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "reasoning_tokens": 2,
        },
        cost=0.004,
        cost_source="provider_observed",
        billing_mode="metered",
        marginal_cost=0.004,
        cache_hit=0,
        finish_reason="stop",
        latency_s=1.25,
        error=None,
        caller="test",
        task="receipt-test",
        trace_id=trace_id,
        logical_call_id=logical_call_id,
        call_fingerprint="a" * 64,
        schema_hash="b" * 64,
        execution_path="native_schema",
        retry_count=0,
    )

    receipts = get_llm_call_receipts(logical_call_id=logical_call_id)

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.latency_s == 1.25
    assert receipt.prompt_tokens == 11
    assert receipt.reasoning_tokens == 2
    assert receipt.cost_usd == 0.004
    assert receipt.cost_status == "observed"
    assert receipt.request_fingerprint == "a" * 64
    assert receipt.prompt_sha256 is None
    assert receipt.schema_sha256 == "b" * 64
    assert receipt.response_sha256 is not None
    assert "private prompt" not in receipt.model_dump_json()
    assert "private response" not in receipt.model_dump_json()
    _close_legacy_test_db()


def test_query_requires_one_identity() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        get_llm_call_receipts()
