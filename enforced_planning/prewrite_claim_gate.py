"""Typed facade for digest-bound pre-write claim authorization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from enforced_planning import coordination_claims
from enforced_planning.prewrite_claim_fast import (
    DEFAULT_RECEIPT_PATH,
    FastPreWriteError,
    adapt_native_payload,
    evaluate_request_fast,
)
from enforced_planning.prewrite_claim_projection import (
    ProjectionBuildError,
    projection_is_current,
    write_projection,
)


PreWriteMode = Literal["off", "observe", "enforce"]
PreWriteClient = Literal["codex", "claude-code"]
PreWriteDecisionKind = Literal["allow", "observe_violation", "deny"]

DEFAULT_CACHE_DIR = Path.home() / ".claude" / "coordination" / "prewrite-cache-v1"


class HookPayloadError(ValueError):
    """Raised when a native hook payload cannot prove its write targets."""


class PreWriteEvaluationError(ValueError):
    """Raised when repository or claim identity cannot be evaluated."""


class StrictContract(BaseModel):
    """Reject unknown fields on durable pre-write contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PreWriteRequestV1(StrictContract):
    """Client-neutral description of one native write attempt."""

    schema_version: Literal["1.0"] = "1.0"
    client: PreWriteClient = Field(description="Native client producing the hook event.")
    hook_event_name: Literal["PreToolUse"] = Field(description="Only the pre-mutation event is valid.")
    tool_name: str = Field(min_length=1, description="Canonical native tool name.")
    session_id: str = Field(min_length=1, description="Canonical client-prefixed session identity.")
    cwd: str = Field(min_length=1, description="Native session working directory.")
    target_paths: tuple[str, ...] = Field(min_length=1, description="Candidate paths before mutation.")


class PreWriteDecisionV1(StrictContract):
    """One attributable authorization decision returned before mutation."""

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=r"^prewrite_[0-9a-f]{32}$")
    decision: PreWriteDecisionKind
    mode: PreWriteMode
    reason_code: str = Field(min_length=1)
    client: PreWriteClient
    session_id: str = Field(min_length=1)
    repo_root: str | None = None
    worktree_path: str | None = None
    branch: str | None = None
    normalized_target_paths: tuple[str, ...] = ()
    claim_project: str | None = None
    claim_scope: str | None = None
    claim_source_file: str | None = None
    details: tuple[str, ...] = ()
    recovery: str | None = None
    elapsed_ms: float = Field(ge=0)
    cache_hit: bool = False


class PreWriteReceiptV1(StrictContract):
    """Append-only local evidence for one pre-write decision."""

    schema_version: Literal["1.0"] = "1.0"
    recorded_at: AwareDatetime
    receipt_id: str
    decision: PreWriteDecisionKind
    mode: PreWriteMode
    reason_code: str
    client: PreWriteClient
    session_id: str
    repo_root: str | None
    worktree_path: str | None
    branch: str | None
    normalized_target_paths: tuple[str, ...]
    claim_project: str | None
    claim_scope: str | None
    claim_source_file: str | None
    details: tuple[str, ...]
    elapsed_ms: float
    cache_hit: bool


def adapt_hook_payload(payload: dict[str, Any], *, client: PreWriteClient) -> PreWriteRequestV1:
    """Normalize one supported native event into the typed public contract."""

    try:
        normalized = adapt_native_payload(payload, client=client)
    except FastPreWriteError as exc:
        raise HookPayloadError(str(exc)) from exc
    return PreWriteRequestV1.model_validate(normalized)


def load_prewrite_mode(repo_root: Path) -> PreWriteMode:
    """Read the explicit portable mode; absence is safely disabled."""

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload is None:
        return "off"
    if not isinstance(payload, dict):
        raise PreWriteEvaluationError(f"{config_path} must contain a YAML mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise PreWriteEvaluationError("meta-process.yaml meta_process must be a mapping")
    claims = meta_process.get("claims", {})
    if claims is None:
        return "off"
    if not isinstance(claims, dict):
        raise PreWriteEvaluationError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise PreWriteEvaluationError(
            "claims.prewrite_mode must be one of: off, observe, enforce"
        )
    return cast(PreWriteMode, mode)


def evaluate_prewrite(
    request: PreWriteRequestV1,
    *,
    mode: PreWriteMode,
    claims_dir: Path = coordination_claims.CLAIMS_DIR,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> PreWriteDecisionV1:
    """Validate through the same engine as the native CLI.

    Library callers may synchronously regenerate the derived projection.  The
    native hook never does so: stale projection state is a visible decision,
    keeping hook latency and authority behavior deterministic.
    """

    projection_path = cache_dir.expanduser().resolve() / "authority-projection-v1.json"
    projection_hit = projection_is_current(
        claims_dir=claims_dir,
        projection_path=projection_path,
    )
    if mode != "off" and not projection_hit:
        try:
            write_projection(
                claims_dir=claims_dir,
                projection_path=projection_path,
            )
        except (OSError, ProjectionBuildError, ValueError):
            # The shared engine will emit a typed stale-projection decision.
            pass
    try:
        raw = evaluate_request_fast(
            request.model_dump(exclude={"schema_version"}),
            mode=mode,
            claims_dir=claims_dir,
            projection_path=projection_path,
            receipt_path=receipt_path,
            cache_hit=projection_hit,
        )
    except FastPreWriteError as exc:
        raise PreWriteEvaluationError(str(exc)) from exc
    return PreWriteDecisionV1.model_validate(raw)


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_RECEIPT_PATH",
    "HookPayloadError",
    "PreWriteDecisionV1",
    "PreWriteEvaluationError",
    "PreWriteMode",
    "PreWriteReceiptV1",
    "PreWriteRequestV1",
    "adapt_hook_payload",
    "evaluate_prewrite",
    "load_prewrite_mode",
]
