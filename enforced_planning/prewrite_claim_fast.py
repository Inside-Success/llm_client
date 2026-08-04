"""Dependency-light pre-write decisions over a canonical claim projection.

This module intentionally uses only the Python standard library.  The YAML
registry is authoritative; this runtime accepts a projection only when its
digest exactly matches the current registry.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"
DEFAULT_PROJECTION_PATH = (
    Path.home() / ".claude" / "coordination" / "prewrite-authority-v1.json"
)
DEFAULT_RECEIPT_PATH = (
    Path.home() / ".claude" / "coordination" / "prewrite-events-v1.jsonl"
)
LIVE_STATUSES = {"active", "blocked", "handoff"}
PROJECTION_FIELDS = {
    "schema_version",
    "generated_at",
    "claims_dir",
    "registry_digest",
    "claims",
}
CLAIM_FIELDS = {
    "agent",
    "projects",
    "scope",
    "claim_type",
    "session_id",
    "repo_root",
    "worktree_path",
    "branch",
    "write_paths",
    "expires_at",
    "heartbeat_at",
    "status",
    "source_file",
    "source_sha256",
    "static_issues",
}

_CUSTOM_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
_CUSTOM_MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")
_UNIFIED_PATCH_PATH = re.compile(r"^(?:---|\+\+\+) (.+)$")


class FastPreWriteError(ValueError):
    """Raised when a hook request cannot be normalized safely."""


def registry_digest(claims_dir: Path) -> str:
    """Hash every YAML authority record deterministically without parsing it."""

    digest = hashlib.sha256()
    if not claims_dir.exists():
        return digest.hexdigest()
    for path in sorted(claims_dir.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def projection_path_for(claims_dir: Path) -> Path:
    """Return the default derived projection path for one registry."""

    resolved = claims_dir.expanduser().resolve()
    if resolved == DEFAULT_CLAIMS_DIR.expanduser().resolve():
        return DEFAULT_PROJECTION_PATH
    return resolved.parent / f"{resolved.name}-prewrite-authority-v1.json"


def _nonempty(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FastPreWriteError(f"PreToolUse payload requires non-empty {field!r}")
    return value.strip()


def _patch_paths(command: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in command.splitlines():
        match = _CUSTOM_PATCH_PATH.match(line) or _CUSTOM_MOVE_PATH.match(line)
        if match:
            paths.append(match.group(1).strip())
            continue
        unified = _UNIFIED_PATCH_PATH.match(line)
        if unified:
            candidate = unified.group(1).strip().split("\t", 1)[0]
            if candidate == "/dev/null":
                continue
            if candidate.startswith(("a/", "b/")):
                candidate = candidate[2:]
            paths.append(candidate)
    return tuple(dict.fromkeys(path for path in paths if path))


def adapt_native_payload(payload: dict[str, Any], *, client: str) -> dict[str, Any]:
    """Normalize one supported native event without retaining write contents."""

    if not isinstance(payload, dict):
        raise FastPreWriteError("PreToolUse payload must be a JSON object")
    if client not in {"codex", "claude-code"}:
        raise FastPreWriteError(f"Unsupported pre-write client: {client!r}")
    event_name = _nonempty(payload, "hook_event_name")
    if event_name != "PreToolUse":
        raise FastPreWriteError(f"Unsupported hook event: {event_name!r}")
    tool_name = _nonempty(payload, "tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise FastPreWriteError("PreToolUse payload requires object field 'tool_input'")

    if client == "codex":
        if tool_name != "apply_patch":
            raise FastPreWriteError(f"Unsupported Codex pre-write tool: {tool_name!r}")
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            raise FastPreWriteError("Codex apply_patch requires string tool_input.command")
        target_paths = _patch_paths(command)
        if not target_paths:
            raise FastPreWriteError("Codex apply_patch payload contains no provable target paths")
    else:
        if tool_name not in {"Edit", "Write"}:
            raise FastPreWriteError(f"Unsupported Claude pre-write tool: {tool_name!r}")
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise FastPreWriteError(f"Claude {tool_name} requires string tool_input.file_path")
        target_paths = (file_path.strip(),)

    raw_session = _nonempty(payload, "session_id")
    session_id = raw_session if raw_session.startswith(f"{client}:") else f"{client}:{raw_session}"
    return {
        "client": client,
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "session_id": session_id,
        "cwd": _nonempty(payload, "cwd"),
        "target_paths": target_paths,
    }


def _git(path: Path, *args: str, allow_failure: bool = False) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    if allow_failure:
        return None
    detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
    raise FastPreWriteError(f"git {' '.join(args)} failed: {detail}")


def _repository_context(request: dict[str, Any]) -> dict[str, Any]:
    cwd = Path(str(request["cwd"])).expanduser().resolve()
    identity = _git(
        cwd,
        "rev-parse",
        "--show-toplevel",
        "--path-format=absolute",
        "--git-common-dir",
        "--abbrev-ref",
        "HEAD",
    )
    assert identity is not None
    parts = identity.splitlines()
    if len(parts) != 3:
        raise FastPreWriteError("Git identity response did not contain worktree, common dir, and branch")
    worktree = Path(parts[0]).resolve()
    common_git = Path(parts[1]).resolve()
    if common_git.name != ".git":
        raise FastPreWriteError(f"unsupported Git common directory: {common_git}")
    repo_root = common_git.parent
    branch = parts[2].strip()
    if not branch:
        raise FastPreWriteError("Pre-write enforcement requires a named Git branch")

    normalized: list[str] = []
    for raw_path in request["target_paths"]:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = worktree / candidate
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(worktree)
        except ValueError as exc:
            raise FastPreWriteError(f"target path escapes active worktree: {raw_path}") from exc
        value = relative.as_posix()
        if value in {"", "."}:
            raise FastPreWriteError("target path must identify a file below the worktree root")
        normalized.append(value)
    return {
        "worktree_path": str(worktree),
        "repo_root": str(repo_root),
        "branch": branch,
        "normalized_target_paths": tuple(dict.fromkeys(normalized)),
    }


def _load_projection(path: Path, *, claims_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict) or set(payload) != PROJECTION_FIELDS:
        return None, "projection fields do not match PreWriteAuthorityProjectionV1"
    if (
        payload.get("schema_version") != "1.0"
        or not isinstance(payload.get("generated_at"), str)
        or not isinstance(payload.get("claims_dir"), str)
        or not isinstance(payload.get("registry_digest"), str)
        or not isinstance(payload.get("claims"), list)
    ):
        return None, "projection schema is invalid"
    resolved_claims = str(claims_dir.expanduser().resolve())
    if payload.get("claims_dir") != resolved_claims:
        return None, "projection claims_dir does not match the requested registry"
    try:
        current_digest = registry_digest(claims_dir)
    except OSError as exc:
        return None, f"claim registry digest failed: {exc}"
    if payload.get("registry_digest") != current_digest:
        return None, "projection registry digest is stale"
    for claim in payload["claims"]:
        if not _valid_projected_claim(claim):
            return None, "projected claim fields are invalid"
    return payload, None


def _valid_projected_claim(claim: object) -> bool:
    """Validate the dependency-light view of PreWriteAuthorityClaimV1."""

    if not isinstance(claim, dict) or set(claim) != CLAIM_FIELDS:
        return False
    string_fields = {
        "agent",
        "scope",
        "claim_type",
        "session_id",
        "repo_root",
        "worktree_path",
        "branch",
        "status",
        "source_file",
        "source_sha256",
    }
    if any(not isinstance(claim.get(field), str) for field in string_fields):
        return False
    for field in ("projects", "write_paths", "static_issues"):
        value = claim.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False
    for field in ("expires_at", "heartbeat_at"):
        if claim.get(field) is not None and not isinstance(claim.get(field), str):
            return False
    return True


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _heartbeat_window() -> timedelta:
    raw = os.environ.get("COORDINATION_HEARTBEAT_STALE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else 120.0
    except ValueError:
        minutes = 120.0
    if minutes <= 0:
        minutes = 120.0
    return timedelta(minutes=minutes)


def _default_ref(repo_root: Path) -> tuple[str, str] | None:
    remote = _git(
        repo_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        allow_failure=True,
    )
    candidates = [remote] if remote else []
    candidates.extend(["main", "master"])
    for candidate in candidates:
        if not candidate:
            continue
        ref = (
            f"refs/remotes/{candidate}"
            if candidate.startswith("origin/")
            else f"refs/heads/{candidate}"
        )
        exists = _git(repo_root, "show-ref", "--verify", ref, allow_failure=True)
        if exists is not None:
            name = candidate.split("/", 1)[1] if candidate.startswith("origin/") else candidate
            return name, ref
    return None


def _dynamic_claim_issues(claim: dict[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    now = datetime.now(timezone.utc)
    expires = _parse_time(claim.get("expires_at"))
    if expires is not None and expires < now:
        issues.append("expired_claim")
    heartbeat = _parse_time(claim.get("heartbeat_at"))
    if claim.get("session_id"):
        if heartbeat is None:
            issues.append("invalid_or_missing_heartbeat_at")
        elif now - heartbeat > _heartbeat_window():
            issues.append("stale_session_heartbeat")

    worktree_raw = claim.get("worktree_path")
    repo_raw = claim.get("repo_root")
    branch = claim.get("branch")
    if not isinstance(worktree_raw, str) or not Path(worktree_raw).expanduser().exists():
        issues.append("missing_worktree_on_disk")
        return tuple(dict.fromkeys(issues))
    if not isinstance(repo_raw, str) or not isinstance(branch, str):
        return tuple(dict.fromkeys(issues))
    repo_root = Path(repo_raw).expanduser().resolve()
    branch_ref = f"refs/heads/{branch}"
    if _git(repo_root, "show-ref", "--verify", branch_ref, allow_failure=True) is None:
        issues.append("missing_branch_ref")
        return tuple(dict.fromkeys(issues))
    default = _default_ref(repo_root)
    if default and default[0] != branch:
        revisions = _git(
            repo_root,
            "rev-parse",
            branch_ref,
            default[1],
            allow_failure=True,
        )
        revision_lines = revisions.splitlines() if revisions is not None else []
        if len(revision_lines) != 2 or revision_lines[0] == revision_lines[1]:
            return tuple(dict.fromkeys(issues))
        merged = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", branch_ref, default[1]],
            capture_output=True,
            check=False,
        )
        if merged.returncode == 0:
            issues.append("merged_active_claim_requires_disposition")
    return tuple(dict.fromkeys(issues))


def _path_is_claimed(target: str, claimed_path: str) -> bool:
    normalized = claimed_path.strip().replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        return True
    return target == normalized or target.startswith(f"{normalized}/")


def _record_receipt(path: Path, decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = {
        key: value
        for key, value in decision.items()
        if key != "recovery"
    }
    receipt["recorded_at"] = datetime.now(timezone.utc).isoformat()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _decision(
    *,
    started: float,
    request: dict[str, Any],
    mode: str,
    decision: str,
    reason_code: str,
    context: dict[str, Any] | None,
    claim: dict[str, Any] | None = None,
    details: tuple[str, ...] = (),
    recovery: str | None = None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "receipt_id": f"prewrite_{uuid.uuid4().hex}",
        "decision": decision,
        "mode": mode,
        "reason_code": reason_code,
        "client": request["client"],
        "session_id": request["session_id"],
        "repo_root": context["repo_root"] if context else None,
        "worktree_path": context["worktree_path"] if context else None,
        "branch": context["branch"] if context else None,
        "normalized_target_paths": list(context["normalized_target_paths"]) if context else [],
        "claim_project": claim["projects"][0] if claim and claim["projects"] else None,
        "claim_scope": claim["scope"] if claim else None,
        "claim_source_file": claim["source_file"] if claim else None,
        "details": list(details),
        "recovery": recovery,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "cache_hit": cache_hit,
    }


def evaluate_request_fast(
    request: dict[str, Any],
    *,
    mode: str,
    claims_dir: Path = DEFAULT_CLAIMS_DIR,
    projection_path: Path | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    cache_hit: bool = True,
) -> dict[str, Any]:
    """Evaluate one normalized request and append its durable receipt."""

    if mode not in {"off", "observe", "enforce"}:
        raise FastPreWriteError("mode must be one of: off, observe, enforce")
    started = time.perf_counter()
    try:
        context = _repository_context(request)
    except FastPreWriteError as exc:
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow" if mode == "off" else ("observe_violation" if mode == "observe" else "deny"),
            reason_code="repository_identity_unavailable",
            context=None,
            details=(str(exc),),
            recovery="Run the write from a named branch in a governed Git worktree.",
        )
        _record_receipt(receipt_path, result)
        return result

    if mode == "off":
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code="mode_off",
            context=context,
        )
        _record_receipt(receipt_path, result)
        return result

    resolved_claims = claims_dir.expanduser().resolve()
    resolved_projection = (projection_path or projection_path_for(resolved_claims)).expanduser().resolve()
    projection, projection_error = _load_projection(
        resolved_projection,
        claims_dir=resolved_claims,
    )
    if projection is None:
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="observe_violation" if mode == "observe" else "deny",
            reason_code="projection_unavailable_or_stale",
            context=context,
            details=(projection_error or "projection unavailable",),
            recovery=(
                "Run python scripts/refresh_prewrite_claim_projection.py "
                f"--claims-dir {resolved_claims} --projection-path {resolved_projection}"
            ),
        )
        _record_receipt(receipt_path, result)
        return result

    candidates = [
        claim
        for claim in projection["claims"]
        if claim["agent"] == request["client"]
        and claim["session_id"] == request["session_id"]
        and Path(claim["worktree_path"]).expanduser().resolve() == Path(context["worktree_path"])
        and Path(claim["repo_root"]).expanduser().resolve() == Path(context["repo_root"])
        and claim["branch"] == context["branch"]
    ]
    claim: dict[str, Any] | None = None
    authorized = False
    reason_code = "exact_live_claim"
    details: tuple[str, ...] = ()
    recovery: str | None = None
    if not candidates:
        reason_code = "no_exact_claim"
        recovery = "Create or resume an exact claimed worktree lane for this session before editing."
    elif len(candidates) > 1:
        reason_code = "ambiguous_exact_claim"
        details = tuple(sorted(f"{item['projects'][0]}:{item['scope']}" for item in candidates))
        recovery = "Close or reconcile duplicate live claims before editing."
    else:
        claim = candidates[0]
        health_issues = tuple(dict.fromkeys([*claim["static_issues"], *_dynamic_claim_issues(claim)]))
        if health_issues:
            reason_code = "claim_not_healthy"
            details = health_issues
            recovery = "Repair or resume the claim through the sanctioned session workflow."
        else:
            outside = tuple(
                target
                for target in context["normalized_target_paths"]
                if not any(_path_is_claimed(target, claimed) for claimed in claim["write_paths"])
            )
            if outside:
                reason_code = "path_outside_claim"
                details = outside
                recovery = "Use a separately claimed lane or update the declared write scope before editing."
            else:
                authorized = True

    result = _decision(
        started=started,
        request=request,
        mode=mode,
        decision="allow" if authorized else ("observe_violation" if mode == "observe" else "deny"),
        reason_code=reason_code,
        context=context,
        claim=claim,
        details=details,
        recovery=recovery,
        cache_hit=cache_hit,
    )
    _record_receipt(receipt_path, result)
    return result


def evaluate_prewrite_fast(
    payload: dict[str, Any],
    *,
    client: str,
    mode: str,
    claims_dir: Path = DEFAULT_CLAIMS_DIR,
    projection_path: Path | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
) -> dict[str, Any]:
    """Normalize and evaluate one native hook payload."""

    request = adapt_native_payload(payload, client=client)
    return evaluate_request_fast(
        request,
        mode=mode,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=receipt_path,
    )


__all__ = [
    "DEFAULT_CLAIMS_DIR",
    "DEFAULT_PROJECTION_PATH",
    "DEFAULT_RECEIPT_PATH",
    "FastPreWriteError",
    "adapt_native_payload",
    "evaluate_prewrite_fast",
    "evaluate_request_fast",
    "projection_path_for",
    "registry_digest",
]
