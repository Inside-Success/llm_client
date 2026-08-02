"""Compile canonical YAML claims into a digest-bound pre-write projection."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict

from enforced_planning import coordination_claims
from enforced_planning.prewrite_claim_fast import projection_path_for, registry_digest


class ProjectionBuildError(ValueError):
    """Raised when canonical claim state cannot be projected safely."""


class StrictProjectionContract(BaseModel):
    """Reject unknown fields on the local projection contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PreWriteAuthorityClaimV1(StrictProjectionContract):
    """Normalized claim facts consumed by the dependency-light gate."""

    agent: str
    projects: tuple[str, ...]
    scope: str
    claim_type: str
    session_id: str
    repo_root: str
    worktree_path: str
    branch: str
    write_paths: tuple[str, ...]
    expires_at: str | None
    heartbeat_at: str | None
    status: str
    source_file: str
    source_sha256: str
    static_issues: tuple[str, ...]


class PreWriteAuthorityProjectionV1(StrictProjectionContract):
    """Replaceable projection whose digest binds it to YAML authority."""

    schema_version: Literal["1.0"] = "1.0"
    generated_at: AwareDatetime
    claims_dir: str
    registry_digest: str
    claims: tuple[PreWriteAuthorityClaimV1, ...]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_projection_claims(claims_dir: Path) -> list[coordination_claims.ClaimRecord]:
    """Load valid unexpired claims and fail on unreadable registry records."""

    if not claims_dir.exists():
        return []
    claims: list[coordination_claims.ClaimRecord] = []
    now = datetime.now(timezone.utc)
    for claim_file in sorted(claims_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ProjectionBuildError(f"Cannot parse claim {claim_file}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProjectionBuildError(f"Claim {claim_file} must contain a YAML mapping")
        raw_status = payload.get("status", "active")
        if isinstance(raw_status, str) and raw_status.strip().lower() not in coordination_claims.LIVE_STATUSES:
            continue
        raw_expires = payload.get("expires_at")
        expires = _parse_time(raw_expires if isinstance(raw_expires, str) else None)
        if expires is not None and expires < now:
            continue
        claim = coordination_claims.normalize_claim(payload, source_file=str(claim_file.resolve()))
        if claim is None:
            raise ProjectionBuildError(f"Claim {claim_file} cannot be normalized")
        if claim.is_live():
            claims.append(claim)
    return claims


def build_projection(*, claims_dir: Path) -> PreWriteAuthorityProjectionV1:
    """Build a validated projection without mutating local state."""

    resolved = claims_dir.expanduser().resolve()
    digest_before = registry_digest(resolved)
    claims = _load_projection_claims(resolved)
    digest_after = registry_digest(resolved)
    if digest_before != digest_after:
        raise ProjectionBuildError(
            "Claim registry changed while the pre-write projection was being built"
        )
    projected: list[PreWriteAuthorityClaimV1] = []
    for claim in claims:
        # Retain unhealthy claims so the fast evaluator can return
        # claim_not_healthy rather than accidentally treating them as absent.
        session_id = claim.session_id or ""
        repo_root = claim.repo_root or ""
        worktree_path = claim.worktree_path or ""
        branch = claim.branch or ""
        source_file = claim.source_file or ""
        source_path = Path(source_file) if source_file else None
        source_sha = (
            hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source_path is not None and source_path.is_file()
            else ""
        )
        projected.append(
            PreWriteAuthorityClaimV1(
                agent=claim.agent,
                projects=tuple(claim.projects),
                scope=claim.scope,
                claim_type=claim.claim_type,
                session_id=session_id,
                repo_root=repo_root,
                worktree_path=worktree_path,
                branch=branch,
                write_paths=tuple(claim.write_paths),
                expires_at=claim.expires_at,
                heartbeat_at=claim.heartbeat_at,
                status=claim.status,
                source_file=source_file,
                source_sha256=source_sha,
                static_issues=tuple(
                    coordination_claims.coordination_health_issues(
                        claim,
                        active_claims=claims,
                    )
                ),
            )
        )
    return PreWriteAuthorityProjectionV1(
        generated_at=datetime.now(timezone.utc),
        claims_dir=str(resolved),
        registry_digest=digest_after,
        claims=tuple(projected),
    )


def write_projection(
    *,
    claims_dir: Path,
    projection_path: Path | None = None,
) -> PreWriteAuthorityProjectionV1:
    """Atomically replace one derived projection after full validation."""

    resolved_claims = claims_dir.expanduser().resolve()
    resolved_projection = (
        projection_path or projection_path_for(resolved_claims)
    ).expanduser().resolve()
    projection = build_projection(claims_dir=resolved_claims)
    resolved_projection.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=resolved_projection.parent,
            prefix=f".{resolved_projection.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(projection.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, resolved_projection)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return projection


def projection_is_current(*, claims_dir: Path, projection_path: Path | None = None) -> bool:
    """Return whether one readable validated projection matches YAML authority."""

    resolved_claims = claims_dir.expanduser().resolve()
    resolved_projection = (
        projection_path or projection_path_for(resolved_claims)
    ).expanduser().resolve()
    try:
        projection = PreWriteAuthorityProjectionV1.model_validate_json(
            resolved_projection.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    return (
        projection.claims_dir == str(resolved_claims)
        and projection.registry_digest == registry_digest(resolved_claims)
    )


__all__ = [
    "PreWriteAuthorityClaimV1",
    "PreWriteAuthorityProjectionV1",
    "ProjectionBuildError",
    "build_projection",
    "projection_is_current",
    "write_projection",
]
