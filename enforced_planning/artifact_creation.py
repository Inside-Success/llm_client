"""Evaluate and observe governed creation of new tracked repository artifacts.

The gate is deliberately narrow: it controls only newly created paths selected
by a repository policy. Existing-file edits remain owned by read-context,
claim, coupling, and ordinary review controls. Durable intent comes from the
repository relationship registry; the hook never invents an authority or
silently manufactures a registration.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
import json
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any, Literal
import uuid

import yaml  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from enforced_planning.prewrite_claim_fast import FastPreWriteError, adapt_native_payload


ArtifactMode = Literal["off", "observe", "enforce"]
ArtifactDecisionKind = Literal["allow", "observe_violation", "deny"]
FeedbackKind = Literal["friction", "recommendation"]

DEFAULT_RECEIPT_PATH = (
    Path.home() / ".claude" / "coordination" / "artifact-creation-events-v1.jsonl"
)
DEFAULT_FEEDBACK_PATH = (
    Path.home() / ".claude" / "coordination" / "artifact-creation-feedback-v1.jsonl"
)


class ArtifactCreationError(ValueError):
    """Raised when configuration or native input cannot be evaluated safely."""


class StrictContract(BaseModel):
    """Reject unknown fields on durable artifact-governance contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactTargetDecisionV1(StrictContract):
    """One path-level creation decision and its exact policy reason."""

    path: str
    is_new: bool
    controlled: bool
    decision: Literal["allow", "violation"]
    reason_code: str
    rule_id: str | None = None
    artifact_id: str | None = None
    concern_id: str | None = None
    details: tuple[str, ...] = ()


class ArtifactCreationDecisionV1(StrictContract):
    """One aggregate pre-write or staged-candidate artifact decision."""

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=r"^artifact_create_[0-9a-f]{32}$")
    recorded_at: AwareDatetime
    mode: ArtifactMode
    decision: ArtifactDecisionKind
    reason_code: str
    client: str
    tool_name: str
    repo_root: str
    branch: str | None
    target_decisions: tuple[ArtifactTargetDecisionV1, ...]
    elapsed_ms: float = Field(ge=0)
    recovery: str | None = None


class ArtifactPolicyFeedbackV1(StrictContract):
    """Human or agent feedback tied to one concrete gate receipt."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["feedback"] = "feedback"
    feedback_id: str = Field(pattern=r"^artifact_feedback_[0-9a-f]{32}$")
    recorded_at: AwareDatetime
    feedback_type: FeedbackKind
    receipt_id: str
    observation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    status: Literal["open"] = "open"


class ArtifactPolicyFeedbackDispositionV1(StrictContract):
    """Append-only resolution of one prior feedback record."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["feedback_disposition"] = "feedback_disposition"
    disposition_id: str = Field(pattern=r"^artifact_disposition_[0-9a-f]{32}$")
    recorded_at: AwareDatetime
    feedback_id: str = Field(pattern=r"^artifact_feedback_[0-9a-f]{32}$")
    disposition: Literal["resolved", "accepted_risk", "superseded"]
    resolution: str = Field(min_length=1)


class ArtifactRepositoryAuditV1(StrictContract):
    """Current repository findings that require cleanup outside a write event."""

    schema_version: Literal["1.0"] = "1.0"
    recorded_at: AwareDatetime
    repo_root: str
    mode: ArtifactMode
    finding_count: int = Field(ge=0)
    findings: tuple[ArtifactTargetDecisionV1, ...]


def _mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping and fail loudly on any other shape."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ArtifactCreationError(f"cannot read artifact policy input {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactCreationError(f"artifact policy input {path} must be a YAML mapping")
    return payload


def _normalize_path(value: str) -> str:
    """Return one safe repository-relative POSIX path."""

    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    candidate = Path(normalized)
    if not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise ArtifactCreationError(f"artifact target must be a safe repository-relative path: {value!r}")
    return candidate.as_posix()


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded Git query without mutating repository state."""

    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _branch(repo_root: Path) -> str | None:
    """Return the current branch when Git can identify it."""

    result = _git(repo_root, "branch", "--show-current")
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def _is_tracked(repo_root: Path, relative_path: str) -> bool:
    """Return whether a path already belongs to the Git index."""

    result = _git(repo_root, "ls-files", "--error-unmatch", "--", relative_path)
    return result.returncode == 0


def load_artifact_settings(repo_root: Path) -> dict[str, Any]:
    """Load the explicit artifact-creation settings from meta-process.yaml."""

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return {"mode": "off"}
    payload = _mapping(config_path)
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise ArtifactCreationError("meta-process.yaml meta_process must be a mapping")
    settings = meta_process.get("artifact_creation", {}) or {}
    if not isinstance(settings, dict):
        raise ArtifactCreationError("meta-process.yaml artifact_creation must be a mapping")
    mode = settings.get("mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise ArtifactCreationError("artifact_creation.mode must be off, observe, or enforce")
    return {
        "mode": mode,
        "policy_file": str(settings.get("policy_file", "scripts/artifact_directory_policy.yaml")),
        "registry_file": str(settings.get("registry_file", "scripts/relationships.yaml")),
    }


def _load_policy(repo_root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """Load and minimally validate the repository directory policy."""

    policy_path = repo_root / str(settings["policy_file"])
    policy = _mapping(policy_path)
    if policy.get("schema_version") != 1:
        raise ArtifactCreationError(f"{policy_path} schema_version must be 1")
    controlled_globs = policy.get("controlled_globs")
    rules = policy.get("directory_rules")
    if not isinstance(controlled_globs, list) or not all(isinstance(item, str) for item in controlled_globs):
        raise ArtifactCreationError(f"{policy_path} controlled_globs must be a list of strings")
    if not isinstance(rules, list) or not rules:
        raise ArtifactCreationError(f"{policy_path} directory_rules must be a non-empty list")
    return policy


def _artifact_blocks(registry_text: str, registry_path: Path) -> tuple[str, ...]:
    """Return raw top-level artifact records without parsing unrelated registry data."""

    lines = registry_text.splitlines(keepends=True)
    try:
        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.rstrip() in {"artifacts:", "artifacts: []"}
        )
    except StopIteration as exc:
        raise ArtifactCreationError(f"{registry_path} must declare an artifacts list") from exc
    if lines[header_index].rstrip() == "artifacts: []":
        return ()
    start = header_index + 1

    blocks: list[str] = []
    current: list[str] = []
    item_prefix: str | None = None
    for line in lines[start:]:
        stripped = line.lstrip(" ")
        leading = line[: len(line) - len(stripped)]
        if stripped.startswith("- ") and item_prefix is None:
            item_prefix = leading
        is_item = item_prefix is not None and line.startswith(f"{item_prefix}- ")
        if line and not line[0].isspace() and line.strip() and not is_item:
            break
        if is_item:
            if current:
                blocks.append("".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("".join(current))
    return tuple(blocks)


def _block_path(block: str) -> str | None:
    """Read one ordinary artifact path scalar while keeping the scan inexpensive."""

    for line in block.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("path:"):
            continue
        scalar = stripped.split(":", 1)[1].strip()
        if not scalar:
            return None
        if scalar[0] not in {"'", '"'}:
            return scalar
        parsed = yaml.safe_load(f"path: {scalar}\n")
        value = parsed.get("path") if isinstance(parsed, dict) else None
        return value if isinstance(value, str) else None
    return None


def _parse_artifact_block(block: str, registry_path: Path) -> dict[str, Any]:
    """Parse one selected artifact record and fail loud on its local shape."""

    try:
        normalized = block if block.startswith("  - ") else "".join(
            f"  {line}" for line in block.splitlines(keepends=True)
        )
        payload = yaml.safe_load("artifacts:\n" + normalized)
    except yaml.YAMLError as exc:
        raise ArtifactCreationError(
            f"cannot parse selected artifact record in {registry_path}: {exc}"
        ) from exc
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
        raise ArtifactCreationError(
            f"selected artifact record in {registry_path} must be one mapping"
        )
    return artifacts[0]


def _load_artifacts(
    repo_root: Path,
    settings: dict[str, Any],
    *,
    target_paths: tuple[str, ...],
    include_all: bool = False,
) -> list[dict[str, Any]]:
    """Load only target records and canonical-concern records needed by this decision."""

    registry_path = repo_root / str(settings["registry_file"])
    try:
        registry_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactCreationError(f"cannot read artifact registry {registry_path}: {exc}") from exc
    targets = set(target_paths)
    selected: list[dict[str, Any]] = []
    for block in _artifact_blocks(registry_text, registry_path):
        # Concern-bearing records are sparse and are needed to detect two
        # active canonical owners. Ordinary legacy records stay unparsed.
        has_concern = any(
            line.lstrip().startswith("concern_id:") for line in block.splitlines()
        )
        if not include_all and _block_path(block) not in targets and not has_concern:
            continue
        selected.append(_parse_artifact_block(block, registry_path))
    return selected


def _rule_for(path: str, policy: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first exact directory rule matching one controlled path."""

    for rule in policy["directory_rules"]:
        if not isinstance(rule, dict):
            raise ArtifactCreationError("each directory_rules item must be a mapping")
        globs = rule.get("path_globs", [])
        if not isinstance(globs, list) or not all(isinstance(item, str) for item in globs):
            raise ArtifactCreationError("directory rule path_globs must be a list of strings")
        if any(_path_glob_matches(path, pattern) for pattern in globs):
            return rule
    return None


def _path_glob_matches(path: str, pattern: str) -> bool:
    """Match repository globs with segment-local ``*`` and recursive ``**``."""

    path_parts = tuple(part for part in path.strip("/").split("/") if part)
    pattern_parts = tuple(part for part in pattern.strip("/").split("/") if part)

    def match(remaining_path: tuple[str, ...], remaining_pattern: tuple[str, ...]) -> bool:
        if not remaining_pattern:
            return not remaining_path
        head = remaining_pattern[0]
        if head == "**":
            return match(remaining_path, remaining_pattern[1:]) or (
                bool(remaining_path)
                and match(remaining_path[1:], remaining_pattern)
            )
        return bool(remaining_path) and fnmatchcase(remaining_path[0], head) and match(
            remaining_path[1:],
            remaining_pattern[1:],
        )

    return match(path_parts, pattern_parts)


def _intent_for(path: str, artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the unique exact intent record for one proposed path."""

    matches = [item for item in artifacts if item.get("path") == path]
    if len(matches) > 1:
        raise ArtifactCreationError(f"multiple artifact intent records exist for {path}")
    return matches[0] if matches else None


def _nonempty(value: Any) -> bool:
    """Return whether one scalar or collection carries meaningful content."""

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _validate_intent(
    *,
    path: str,
    intent: dict[str, Any],
    rule: dict[str, Any],
    artifacts: list[dict[str, Any]],
    now: datetime,
) -> tuple[list[str], str | None]:
    """Return deterministic business-rule violations plus the concern ID."""

    violations: list[str] = []
    required = (
        "artifact_id",
        "path",
        "kind",
        "owner",
        "concern_id",
        "authority",
        "creation_justification",
        "separate_file_reason",
        "lifecycle",
        "review_triggers",
        "alignment",
    )
    for field_name in required:
        if not _nonempty(intent.get(field_name)):
            violations.append(f"missing required intent field {field_name}")

    kind = intent.get("kind")
    authority = intent.get("authority")
    allowed_kinds = rule.get("allowed_kinds", [])
    allowed_authorities = rule.get("allowed_authorities", [])
    if kind not in allowed_kinds:
        violations.append(f"kind {kind!r} is not allowed by directory rule {rule.get('id')!r}")
    if authority not in allowed_authorities:
        violations.append(f"authority {authority!r} is not allowed by directory rule {rule.get('id')!r}")

    lifecycle = intent.get("lifecycle")
    if not isinstance(lifecycle, dict):
        violations.append("lifecycle must be a mapping")
    else:
        for field_name in ("status", "retirement_condition"):
            if not _nonempty(lifecycle.get(field_name)):
                violations.append(f"lifecycle.{field_name} is required")

    alignment = intent.get("alignment")
    if not isinstance(alignment, dict):
        violations.append("alignment must be a mapping")
    elif not any(_nonempty(alignment.get(key)) for key in ("consumer_refs", "authority_refs", "evidence_refs", "generated_by")):
        violations.append("alignment must provide a discoverability, authority, evidence, or generator edge")

    concern_id = intent.get("concern_id") if isinstance(intent.get("concern_id"), str) else None
    if concern_id and authority == "canonical":
        for other in artifacts:
            if other is intent:
                continue
            other_lifecycle = other.get("lifecycle")
            active = not isinstance(other_lifecycle, dict) or other_lifecycle.get("status") not in {
                "superseded",
                "archived",
                "retired",
            }
            if active and other.get("concern_id") == concern_id and other.get("authority") == "canonical":
                violations.append(
                    f"canonical concern {concern_id!r} is already owned by {other.get('path')!r}"
                )

    if rule.get("generated_only"):
        if not isinstance(alignment, dict) or not _nonempty(alignment.get("generated_by")):
            violations.append("generated directory members require alignment.generated_by")

    if rule.get("quarantine"):
        if authority != "none":
            violations.append("quarantine artifacts must declare authority: none")
        destination = intent.get("destination")
        expires_at = intent.get("expires_at")
        if not _nonempty(destination):
            violations.append("quarantine artifacts require destination")
        if not isinstance(expires_at, str):
            violations.append("quarantine artifacts require ISO-8601 expires_at")
        else:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    raise ValueError("timezone required")
                max_days = int(rule.get("max_ttl_days", 14))
                if expiry <= now:
                    violations.append("quarantine expires_at must be in the future")
                if expiry > now + timedelta(days=max_days):
                    violations.append(f"quarantine expires_at exceeds {max_days}-day maximum")
            except (TypeError, ValueError):
                violations.append("quarantine expires_at must be a timezone-aware ISO-8601 value")

    return violations, concern_id


def evaluate_paths(
    *,
    repo_root: Path,
    target_paths: tuple[str, ...],
    client: str,
    tool_name: str,
    mode: ArtifactMode | None = None,
    force_new_paths: set[str] | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    write_receipt: bool = True,
) -> ArtifactCreationDecisionV1:
    """Evaluate proposed paths and optionally append one local decision receipt."""

    started = time.perf_counter()
    repo_root = repo_root.resolve()
    settings = load_artifact_settings(repo_root)
    selected_mode = mode or settings["mode"]
    if selected_mode not in {"off", "observe", "enforce"}:
        raise ArtifactCreationError(f"unsupported artifact mode {selected_mode!r}")
    now = datetime.now(timezone.utc)
    normalized_paths = tuple(dict.fromkeys(_normalize_path(path) for path in target_paths))
    target_decisions: list[ArtifactTargetDecisionV1] = []

    if selected_mode == "off":
        for path in normalized_paths:
            target_decisions.append(
                ArtifactTargetDecisionV1(
                    path=path,
                    is_new=not _is_tracked(repo_root, path),
                    controlled=False,
                    decision="allow",
                    reason_code="gate_off",
                )
            )
    else:
        policy = _load_policy(repo_root, settings)
        artifacts = _load_artifacts(
            repo_root,
            settings,
            target_paths=normalized_paths,
        )
        forced = {_normalize_path(path) for path in (force_new_paths or set())}
        for path in normalized_paths:
            is_new = path in forced or not _is_tracked(repo_root, path)
            controlled = is_new and any(
                _path_glob_matches(path, pattern)
                for pattern in policy["controlled_globs"]
            )
            if not is_new:
                target_decisions.append(
                    ArtifactTargetDecisionV1(
                        path=path,
                        is_new=False,
                        controlled=False,
                        decision="allow",
                        reason_code="existing_path",
                    )
                )
                continue
            if not controlled:
                target_decisions.append(
                    ArtifactTargetDecisionV1(
                        path=path,
                        is_new=True,
                        controlled=False,
                        decision="allow",
                        reason_code="outside_controlled_globs",
                    )
                )
                continue
            rule = _rule_for(path, policy)
            if rule is None:
                target_decisions.append(
                    ArtifactTargetDecisionV1(
                        path=path,
                        is_new=True,
                        controlled=True,
                        decision="violation",
                        reason_code="directory_not_allowed",
                        details=("No directory rule permits this controlled path.",),
                    )
                )
                continue
            intent = _intent_for(path, artifacts)
            if intent is None:
                target_decisions.append(
                    ArtifactTargetDecisionV1(
                        path=path,
                        is_new=True,
                        controlled=True,
                        decision="violation",
                        reason_code="intent_missing",
                        rule_id=str(rule.get("id", "")) or None,
                        details=(
                            "Register the file in the configured relationship registry before creating it.",
                            "Prefer updating an existing concern owner when one exists.",
                        ),
                    )
                )
                continue
            violations, concern_id = _validate_intent(
                path=path,
                intent=intent,
                rule=rule,
                artifacts=artifacts,
                now=now,
            )
            target_decisions.append(
                ArtifactTargetDecisionV1(
                    path=path,
                    is_new=True,
                    controlled=True,
                    decision="violation" if violations else "allow",
                    reason_code="intent_invalid" if violations else "registered_creation_allowed",
                    rule_id=str(rule.get("id", "")) or None,
                    artifact_id=str(intent.get("artifact_id", "")) or None,
                    concern_id=concern_id,
                    details=tuple(violations),
                )
            )

    has_violation = any(item.decision == "violation" for item in target_decisions)
    if has_violation and selected_mode == "enforce":
        decision: ArtifactDecisionKind = "deny"
    elif has_violation:
        decision = "observe_violation"
    else:
        decision = "allow"
    reason_code = "artifact_policy_violation" if has_violation else "artifact_policy_satisfied"
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = ArtifactCreationDecisionV1(
        receipt_id=f"artifact_create_{uuid.uuid4().hex}",
        recorded_at=now,
        mode=selected_mode,
        decision=decision,
        reason_code=reason_code,
        client=client,
        tool_name=tool_name,
        repo_root=str(repo_root),
        branch=_branch(repo_root),
        target_decisions=tuple(target_decisions),
        elapsed_ms=elapsed_ms,
        recovery=(
            "Update the existing concern owner, or register a distinct allowed artifact and retry. "
            "Use the configured misc quarantine only for expiring non-authoritative material."
            if has_violation
            else None
        ),
    )
    if write_receipt and selected_mode != "off":
        append_jsonl(receipt_path, result.model_dump(mode="json"))
    return result


def evaluate_native_payload(
    payload: dict[str, Any],
    *,
    client: Literal["codex", "claude-code"],
    mode: ArtifactMode | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
) -> ArtifactCreationDecisionV1:
    """Adapt one supported native pre-write payload and evaluate its paths."""

    try:
        request = adapt_native_payload(payload, client=client)
    except FastPreWriteError as exc:
        raise ArtifactCreationError(str(exc)) from exc
    cwd = Path(str(request["cwd"]))
    root_result = _git(cwd, "rev-parse", "--show-toplevel")
    if root_result.returncode != 0:
        raise ArtifactCreationError(root_result.stderr.strip() or "unable to resolve Git worktree")
    repo_root = Path(root_result.stdout.strip()).resolve()
    normalized: list[str] = []
    for raw_path in request["target_paths"]:
        candidate = Path(str(raw_path))
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(repo_root)
            except ValueError as exc:
                raise ArtifactCreationError(f"write target is outside repository: {raw_path}") from exc
        normalized.append(_normalize_path(candidate.as_posix()))
    return evaluate_paths(
        repo_root=repo_root,
        target_paths=tuple(normalized),
        client=client,
        tool_name=str(request["tool_name"]),
        mode=mode,
        receipt_path=receipt_path,
    )


def staged_new_paths(repo_root: Path) -> tuple[str, ...]:
    """Return newly added paths from the current staged candidate."""

    result = _git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=A")
    if result.returncode != 0:
        raise ArtifactCreationError(result.stderr.strip() or "unable to inspect staged files")
    return tuple(_normalize_path(line) for line in result.stdout.splitlines() if line.strip())


def audit_repository(repo_root: Path) -> ArtifactRepositoryAuditV1:
    """Audit retained quarantine and generated records that can decay over time."""

    resolved = repo_root.expanduser().resolve()
    settings = load_artifact_settings(resolved)
    mode = settings["mode"]
    if mode == "off":
        return ArtifactRepositoryAuditV1(
            recorded_at=datetime.now(timezone.utc),
            repo_root=str(resolved),
            mode="off",
            finding_count=0,
            findings=(),
        )
    policy = _load_policy(resolved, settings)
    artifacts = _load_artifacts(
        resolved,
        settings,
        target_paths=(),
        include_all=True,
    )
    now = datetime.now(timezone.utc)
    findings: list[ArtifactTargetDecisionV1] = []
    for intent in artifacts:
        raw_path = intent.get("path")
        if not isinstance(raw_path, str):
            continue
        path = _normalize_path(raw_path)
        rule = _rule_for(path, policy)
        if rule is None or not (rule.get("quarantine") or rule.get("generated_only")):
            continue
        if not _is_tracked(resolved, path):
            continue
        violations, concern_id = _validate_intent(
            path=path,
            intent=intent,
            rule=rule,
            artifacts=artifacts,
            now=now,
        )
        if violations:
            findings.append(
                ArtifactTargetDecisionV1(
                    path=path,
                    is_new=False,
                    controlled=True,
                    decision="violation",
                    reason_code="retained_artifact_invalid",
                    rule_id=str(rule.get("id", "")) or None,
                    artifact_id=str(intent.get("artifact_id", "")) or None,
                    concern_id=concern_id,
                    details=tuple(violations),
                )
            )
    return ArtifactRepositoryAuditV1(
        recorded_at=now,
        repo_root=str(resolved),
        mode=mode,
        finding_count=len(findings),
        findings=tuple(findings),
    )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one durable local JSONL record."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def record_feedback(
    *,
    feedback_type: FeedbackKind,
    receipt_id: str,
    observation: str,
    recommendation: str,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
) -> ArtifactPolicyFeedbackV1:
    """Persist concrete friction or improvement evidence without changing policy."""

    record = ArtifactPolicyFeedbackV1(
        feedback_id=f"artifact_feedback_{uuid.uuid4().hex}",
        recorded_at=datetime.now(timezone.utc),
        feedback_type=feedback_type,
        receipt_id=receipt_id,
        observation=observation.strip(),
        recommendation=recommendation.strip(),
    )
    append_jsonl(feedback_path, record.model_dump(mode="json"))
    return record


def record_feedback_disposition(
    *,
    feedback_id: str,
    disposition: Literal["resolved", "accepted_risk", "superseded"],
    resolution: str,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
) -> ArtifactPolicyFeedbackDispositionV1:
    """Append a durable disposition without rewriting the original feedback."""

    existing = _read_jsonl(feedback_path)
    matching = [
        row
        for row in existing
        if row.get("record_type", "feedback") == "feedback"
        and row.get("feedback_id") == feedback_id
    ]
    if len(matching) != 1:
        raise ArtifactCreationError(
            f"feedback disposition requires exactly one existing record for {feedback_id}"
        )
    record = ArtifactPolicyFeedbackDispositionV1(
        disposition_id=f"artifact_disposition_{uuid.uuid4().hex}",
        recorded_at=datetime.now(timezone.utc),
        feedback_id=feedback_id,
        disposition=disposition,
        resolution=resolution.strip(),
    )
    append_jsonl(feedback_path, record.model_dump(mode="json"))
    return record


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read valid JSON objects from a local evidence stream and fail on corruption."""

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArtifactCreationError(f"malformed JSONL at {resolved}:{line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ArtifactCreationError(f"JSONL row at {resolved}:{line_number} is not an object")
        rows.append(payload)
    return rows


def build_report(
    *,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build a step-down-friendly enforcement, latency, and feedback report."""

    receipts = _read_jsonl(receipt_path)
    if repo_root is not None:
        root = str(repo_root.expanduser().resolve())
        receipts = [row for row in receipts if row.get("repo_root") == root]
    feedback_stream = _read_jsonl(feedback_path)
    feedback = [
        row
        for row in feedback_stream
        if row.get("record_type", "feedback") == "feedback"
    ]
    dispositions = [
        row
        for row in feedback_stream
        if row.get("record_type") == "feedback_disposition"
    ]
    receipt_ids = {str(row.get("receipt_id")) for row in receipts}
    feedback = [row for row in feedback if row.get("receipt_id") in receipt_ids]
    feedback_ids = {str(row.get("feedback_id")) for row in feedback}
    dispositions = [row for row in dispositions if row.get("feedback_id") in feedback_ids]
    latest_disposition = {
        str(row.get("feedback_id")): row
        for row in dispositions
    }
    open_feedback = [
        row
        for row in feedback
        if str(row.get("feedback_id")) not in latest_disposition
    ]
    resolved_feedback = [
        {
            "feedback": row,
            "disposition": latest_disposition[str(row.get("feedback_id"))],
        }
        for row in feedback
        if str(row.get("feedback_id")) in latest_disposition
    ]
    latencies = [float(row["elapsed_ms"]) for row in receipts if isinstance(row.get("elapsed_ms"), (int, float))]
    reason_counts: Counter[str] = Counter()
    path_counts: Counter[str] = Counter()
    for receipt in receipts:
        for item in receipt.get("target_decisions", []) or []:
            if isinstance(item, dict):
                reason_counts[str(item.get("reason_code", "unknown"))] += 1
                path_counts[str(item.get("path", "unknown"))] += 1
    sorted_latency = sorted(latencies)

    def percentile(value: float) -> float | None:
        if not sorted_latency:
            return None
        index = min(len(sorted_latency) - 1, max(0, round((len(sorted_latency) - 1) * value)))
        return round(sorted_latency[index], 3)

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root.expanduser().resolve()) if repo_root else None,
        "receipt_count": len(receipts),
        "decision_counts": dict(Counter(str(row.get("decision", "unknown")) for row in receipts)),
        "reason_counts": dict(sorted(reason_counts.items())),
        "most_frequent_paths": path_counts.most_common(20),
        "latency_ms": {
            "median": round(statistics.median(sorted_latency), 3) if sorted_latency else None,
            "p95": percentile(0.95),
            "max": round(max(sorted_latency), 3) if sorted_latency else None,
        },
        "feedback_counts": dict(Counter(str(row.get("feedback_type", "unknown")) for row in feedback)),
        "disposition_counts": dict(
            Counter(str(row.get("disposition", "unknown")) for row in dispositions)
        ),
        "open_feedback": open_feedback,
        "resolved_feedback": resolved_feedback,
        "step_down": {
            "receipt_path": str(receipt_path.expanduser().resolve()),
            "feedback_path": str(feedback_path.expanduser().resolve()),
            "receipt_ids": sorted(receipt_ids),
        },
    }


__all__ = [
    "ArtifactCreationDecisionV1",
    "ArtifactCreationError",
    "ArtifactPolicyFeedbackV1",
    "ArtifactPolicyFeedbackDispositionV1",
    "ArtifactRepositoryAuditV1",
    "ArtifactTargetDecisionV1",
    "DEFAULT_FEEDBACK_PATH",
    "DEFAULT_RECEIPT_PATH",
    "append_jsonl",
    "audit_repository",
    "build_report",
    "evaluate_native_payload",
    "evaluate_paths",
    "load_artifact_settings",
    "record_feedback",
    "record_feedback_disposition",
    "staged_new_paths",
]
