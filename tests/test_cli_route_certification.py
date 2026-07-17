"""Subprocess coverage for exact route-certification queries."""

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

from llm_client.route_certification import (
    RouteCertificationObservation,
    RouteCertificationStore,
)


def _query(root: Path, schema_sha256: str) -> subprocess.CompletedProcess[str]:
    """Run one exact provider route query through the public CLI."""

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "llm_client",
            "route-certification",
            "query",
            "--root",
            str(root),
            "--resolved-model",
            "openrouter/x-ai/grok-4.5",
            "--provider",
            "endpoint-1",
            "--execution-mode",
            "native_json_schema",
            "--schema-class",
            "answer-v1",
            "--schema-sha256",
            schema_sha256,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_reports_certification_and_latest_health(tmp_path: Path) -> None:
    """Agents can inspect durable proof without reading JSON files manually."""

    schema_sha256 = "a" * 64
    observation = RouteCertificationObservation.build(
        requested_model="very_intelligent",
        resolved_model="openrouter/x-ai/grok-4.5",
        upstream_provider_name="XAI",
        upstream_provider_endpoint="endpoint-1",
        execution_mode="native_json_schema",
        schema_class="answer-v1",
        schema_sha256=schema_sha256,
        outcome="parseable",
        failure_stage="none",
        logical_call_id="logical-1",
        trace_id="trace-1",
        observed_at=datetime(2026, 7, 16, tzinfo=UTC),
        llm_client_revision="revision-1",
        selected_attempt_receipt_digest="b" * 64,
        evidence_ref="/evidence/orgen1.json",
    )
    RouteCertificationStore(tmp_path).append(observation)

    proc = _query(tmp_path, schema_sha256)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["found"] is True
    assert payload["route"]["transport_certified"] is True
    assert payload["route"]["upstream_provider_name"] == "XAI"
    assert payload["route"]["upstream_provider_endpoint"] == "endpoint-1"


def test_cli_reports_exact_schema_miss_explicitly(tmp_path: Path) -> None:
    """A different schema digest does not inherit another route's proof."""

    proc = _query(tmp_path, "c" * 64)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"found": False}
