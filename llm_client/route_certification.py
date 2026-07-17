"""Persist and query exact structured-output route observations.

Certification is deliberately narrower than model capability: it binds one
resolved model, actual upstream endpoint, execution mode, schema class, and
schema digest to retained runtime evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python


RouteOutcome = Literal[
    "parseable",
    "schema_rejected",
    "capacity_rejected",
    "timeout",
    "invalid_output",
    "local_contract_rejected",
    "semantic_review_rejected",
]


def _digest(payload: object) -> str:
    """Hash one canonical JSON payload for immutable replay."""

    encoded = json.dumps(
        to_jsonable_python(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RouteCertificationObservation(BaseModel):
    """Record one exact route/schema outcome without overgeneralizing it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["route-certification-observation-v1"] = (
        "route-certification-observation-v1"
    )
    observation_id: str = Field(pattern=r"^routeobs1_[0-9a-f]{24}$")
    requested_model: str = Field(min_length=1)
    resolved_model: str = Field(min_length=1)
    upstream_provider_endpoint: str | None = Field(
        default=None,
        min_length=1,
        description="Actual OpenRouter endpoint slug; None means it was not observed."
    )
    execution_mode: Literal["native_json_schema", "instructor", "text"]
    schema_class: str = Field(min_length=1)
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: RouteOutcome
    failure_stage: Literal[
        "none",
        "pre_dispatch",
        "schema_transport",
        "provider_capacity",
        "provider_runtime",
        "local_validation",
        "semantic_review",
    ]
    logical_call_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    observed_at: datetime
    llm_client_revision: str = Field(min_length=1)
    selected_attempt_receipt_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    evidence_ref: str = Field(min_length=1)
    record_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values: object) -> "RouteCertificationObservation":
        """Build deterministic identity and digest from trusted observation fields."""

        payload = {"schema_version": "route-certification-observation-v1", **values}
        digest = _digest(payload)
        return cls.model_validate(
            payload
            | {
                "observation_id": f"routeobs1_{digest[:24]}",
                "record_digest": digest,
            }
        )

    @model_validator(mode="after")
    def _replay_and_validate(self) -> "RouteCertificationObservation":
        """Reject corruption and inconsistent outcome/failure classification."""

        payload = self.model_dump(
            mode="json", exclude={"observation_id", "record_digest"}
        )
        expected = _digest(payload)
        if self.record_digest != expected:
            raise ValueError("route observation digest mismatch")
        if self.observation_id != f"routeobs1_{expected[:24]}":
            raise ValueError("route observation identity mismatch")
        if (self.outcome == "parseable") != (self.failure_stage == "none"):
            raise ValueError("route outcome and failure stage disagree")
        expected_failure_stage = {
            "schema_rejected": "schema_transport",
            "capacity_rejected": "provider_capacity",
            "timeout": "provider_runtime",
            "invalid_output": "local_validation",
            "local_contract_rejected": "local_validation",
            "semantic_review_rejected": "semantic_review",
        }
        if self.outcome != "parseable" and self.failure_stage != expected_failure_stage[
            self.outcome
        ]:
            raise ValueError("route failure outcome is assigned to the wrong stage")
        return self

    @property
    def transport_certifies(self) -> bool:
        """Return whether this observation proves the exact native route worked."""

        return (
            self.outcome == "parseable"
            and self.execution_mode == "native_json_schema"
            and self.upstream_provider_endpoint is not None
            and self.selected_attempt_receipt_digest is not None
        )


class RouteCertificationView(BaseModel):
    """Summarize durable proof separately from the route's latest health."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_model: str
    resolved_model: str
    upstream_provider_endpoint: str | None
    execution_mode: str
    schema_class: str
    schema_sha256: str
    transport_certified: bool
    certification_observation_id: str | None
    latest_outcome: RouteOutcome
    latest_observation_id: str
    observation_count: int = Field(ge=1)


class RouteCertificationStore:
    """Store immutable observations as independently replayable JSON files."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def append(self, observation: RouteCertificationObservation) -> Path:
        """Persist once; identical replay is idempotent and conflict fails loud."""

        observation = RouteCertificationObservation.model_validate(
            observation.model_dump(mode="json")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{observation.observation_id}.json"
        encoded = observation.model_dump_json(indent=2) + "\n"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
        except FileExistsError:
            existing = RouteCertificationObservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if existing != observation:
                raise ValueError("route observation identity conflict") from None
        return path

    def observations(self) -> tuple[RouteCertificationObservation, ...]:
        """Load every record with schema and digest replay validation."""

        if not self.root.exists():
            return ()
        return tuple(
            RouteCertificationObservation.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            for path in sorted(self.root.glob("routeobs1_*.json"))
        )

    def query(
        self,
        *,
        resolved_model: str,
        upstream_provider_endpoint: str | None,
        execution_mode: str,
        schema_class: str,
        schema_sha256: str,
    ) -> RouteCertificationView | None:
        """Return exact-key certification proof and the latest route outcome."""

        matches = [
            item
            for item in self.observations()
            if (
                item.resolved_model,
                item.upstream_provider_endpoint,
                item.execution_mode,
                item.schema_class,
                item.schema_sha256,
            )
            == (
                resolved_model,
                upstream_provider_endpoint,
                execution_mode,
                schema_class,
                schema_sha256,
            )
        ]
        if not matches:
            return None
        latest = max(matches, key=lambda item: (item.observed_at, item.observation_id))
        certified = [item for item in matches if item.transport_certifies]
        proof = min(certified, key=lambda item: (item.observed_at, item.observation_id)) if certified else None
        return RouteCertificationView(
            requested_model=latest.requested_model,
            resolved_model=latest.resolved_model,
            upstream_provider_endpoint=latest.upstream_provider_endpoint,
            execution_mode=latest.execution_mode,
            schema_class=latest.schema_class,
            schema_sha256=latest.schema_sha256,
            transport_certified=proof is not None,
            certification_observation_id=(proof.observation_id if proof else None),
            latest_outcome=latest.outcome,
            latest_observation_id=latest.observation_id,
            observation_count=len(matches),
        )


__all__ = [
    "RouteCertificationObservation",
    "RouteCertificationStore",
    "RouteCertificationView",
    "RouteOutcome",
]
