"""Private sidecar persistence for exact raw structured-attempt content.

Raw bodies stay outside the metadata ledger. Retention is explicitly opt-in;
enabled storage fails loudly because a nullable reference must never imply that
exact bytes are recoverable when persistence actually failed.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

from pydantic import BaseModel, ConfigDict, Field

import llm_client.io_log as _io_log

_ENABLED_ENV = "LLM_CLIENT_STRUCTURED_RAW_ARTIFACTS"
_ROOT_ENV = "LLM_CLIENT_STRUCTURED_RAW_ARTIFACT_ROOT"
_RETENTION_ENV = "LLM_CLIENT_STRUCTURED_RAW_RETENTION_DAYS"
_ARTIFACT_DIRECTORY = "llm_client_structured_raw"
_VERSION = "v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REF_RE = re.compile(
    r"v1/(\d{4}-\d{2}-\d{2})/([0-9a-f]{64})/(\d+)-([0-9a-f]{64})\.raw"
)


class StructuredRawArtifactError(RuntimeError):
    """Raw structured-content storage or verification failed."""


class StructuredRawArtifactWrite(BaseModel):
    """Metadata returned after exact raw bytes are durably persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: str = Field(
        description="Versioned relative reference beneath the configured private root."
    )
    raw_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="SHA-256 computed over the exact persisted UTF-8 bytes.",
    )


def _retention_enabled() -> bool:
    """Parse the explicit raw-retention switch without silent coercion."""

    raw = os.environ.get(_ENABLED_ENV, "off").strip().lower()
    if raw in {"off", "0", "false", "no"}:
        return False
    if raw in {"on", "1", "true", "yes"}:
        return True
    raise StructuredRawArtifactError(
        f"Invalid {_ENABLED_ENV}={raw!r}; expected on or off."
    )


def _artifact_root() -> Path:
    """Resolve the dedicated root, rejecting cwd-dependent configured paths."""

    configured = os.environ.get(_ROOT_ENV)
    if configured is None or not configured.strip():
        return _io_log._data_root / _ARTIFACT_DIRECTORY
    root = Path(configured).expanduser()
    if not root.is_absolute():
        raise StructuredRawArtifactError(
            f"Configured {_ROOT_ENV} must be an absolute path."
        )
    return root


def _retention_days() -> int:
    """Resolve positive raw retention, inheriting general log retention by default."""

    raw = os.environ.get(_RETENTION_ENV)
    if raw is None or not raw.strip():
        return _io_log._get_log_retention_days()
    try:
        parsed = int(raw)
    except ValueError as error:
        raise StructuredRawArtifactError(
            f"Invalid {_RETENTION_ENV}={raw!r}; expected a positive integer."
        ) from error
    if parsed < 1:
        raise StructuredRawArtifactError(
            f"Invalid {_RETENTION_ENV}={raw!r}; expected a positive integer."
        )
    return parsed


def _ensure_private_directory(path: Path) -> None:
    """Create one artifact-owned directory and force owner-only access."""

    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.is_dir() or path.is_symlink():
            raise StructuredRawArtifactError(
                f"Structured raw artifact root is not a private directory: {path}"
            )
        path.chmod(0o700)
    except StructuredRawArtifactError:
        raise
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Cannot prepare structured raw artifact root {path}: {error}"
        ) from error


def _cleanup_expired(root: Path, retention_days: int) -> None:
    """Remove only owned version/date directories older than configured retention."""

    version_root = root / _VERSION
    _ensure_private_directory(version_root)
    cutoff = date.today() - timedelta(days=retention_days)
    try:
        children = tuple(version_root.iterdir())
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Cannot enumerate structured raw artifact root {version_root}: {error}"
        ) from error
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            child_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if child_date < cutoff:
            try:
                shutil.rmtree(child)
            except OSError as error:
                raise StructuredRawArtifactError(
                    f"Cannot remove expired structured raw artifact directory {child}: {error}"
                ) from error


def _ensure_private_tree(root: Path, directory: Path) -> None:
    """Create and restrict every artifact-owned directory beneath the root."""

    _ensure_private_directory(root)
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise StructuredRawArtifactError(
            f"Structured raw artifact directory escapes its root: {directory}"
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        _ensure_private_directory(current)


def prepare_structured_raw_artifact_store() -> bool:
    """Validate enabled storage before provider transport and clean expired data."""

    if not _retention_enabled():
        return False
    if not _io_log._logging_enabled():
        raise StructuredRawArtifactError(
            "Structured raw artifacts are enabled while observability logging is disabled."
        )
    root = _artifact_root()
    _ensure_private_directory(root)
    _cleanup_expired(root, _retention_days())
    try:
        fd, probe_name = tempfile.mkstemp(prefix=".readiness-", dir=root)
        os.fchmod(fd, 0o600)
        os.close(fd)
        Path(probe_name).unlink()
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Structured raw artifact root is not writable: {root}: {error}"
        ) from error
    return True


def _call_key(logical_call_id: str) -> str:
    """Map an exact logical-call identity to a path-safe stable key."""

    if not logical_call_id.strip():
        raise StructuredRawArtifactError("logical_call_id must be nonblank.")
    return hashlib.sha256(logical_call_id.encode("utf-8")).hexdigest()


def _build_ref(
    *, logical_call_id: str, attempt_ordinal: int, raw_sha256: str
) -> str:
    """Build the versioned relative reference for one exact received body."""

    if attempt_ordinal < 0:
        raise StructuredRawArtifactError("attempt_ordinal must be non-negative.")
    return (
        f"{_VERSION}/{date.today().isoformat()}/{_call_key(logical_call_id)}/"
        f"{attempt_ordinal}-{raw_sha256}.raw"
    )


def _validate_ref(
    *,
    artifact_ref: str,
    logical_call_id: str,
    attempt_ordinal: int,
    expected_sha256: str,
) -> Path:
    """Validate reference shape and identity before resolving it beneath the root."""

    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise StructuredRawArtifactError("Expected raw SHA-256 is malformed.")
    pure = PurePosixPath(artifact_ref)
    if pure.is_absolute() or ".." in pure.parts:
        raise StructuredRawArtifactError("Raw artifact reference escapes its root.")
    match = _REF_RE.fullmatch(artifact_ref)
    if match is None:
        raise StructuredRawArtifactError("Raw artifact reference shape is invalid.")
    _day, call_key, ordinal_text, ref_sha256 = match.groups()
    if call_key != _call_key(logical_call_id):
        raise StructuredRawArtifactError("Raw artifact logical-call identity mismatch.")
    if int(ordinal_text) != attempt_ordinal:
        raise StructuredRawArtifactError("Raw artifact attempt ordinal mismatch.")
    if ref_sha256 != expected_sha256:
        raise StructuredRawArtifactError("Raw artifact reference SHA-256 mismatch.")
    configured_root = _artifact_root()
    if configured_root.is_symlink():
        raise StructuredRawArtifactError("Raw artifact root is a symbolic link.")
    root = configured_root.resolve()
    path = (root / Path(*pure.parts)).resolve(strict=False)
    if path != root and root not in path.parents:
        raise StructuredRawArtifactError("Raw artifact reference escapes its root.")
    return path


def write_structured_raw_artifact(
    logical_call_id: str,
    attempt_ordinal: int,
    raw_content: str,
) -> StructuredRawArtifactWrite | None:
    """Persist exact UTF-8 bytes atomically when retention is explicitly enabled."""

    if not prepare_structured_raw_artifact_store():
        return None
    raw_bytes = raw_content.encode("utf-8")
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    artifact_ref = _build_ref(
        logical_call_id=logical_call_id,
        attempt_ordinal=attempt_ordinal,
        raw_sha256=raw_sha256,
    )
    path = _artifact_root() / Path(*PurePosixPath(artifact_ref).parts)
    _ensure_private_tree(_artifact_root(), path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != raw_bytes:
                raise StructuredRawArtifactError(
                    f"Existing raw artifact content contradicts its reference: {artifact_ref}"
                )
        os.chmod(path, 0o600)
    except StructuredRawArtifactError:
        raise
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Cannot persist structured raw artifact {artifact_ref}: {error}"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return StructuredRawArtifactWrite(
        artifact_ref=artifact_ref,
        raw_sha256=raw_sha256,
    )


def read_structured_raw_artifact(
    *,
    artifact_ref: str,
    logical_call_id: str,
    attempt_ordinal: int,
    expected_sha256: str,
) -> bytes:
    """Reopen one exact private artifact and verify identity, mode, and bytes."""

    if not _retention_enabled():
        raise StructuredRawArtifactError("Structured raw artifact retention is disabled.")
    path = _validate_ref(
        artifact_ref=artifact_ref,
        logical_call_id=logical_call_id,
        attempt_ordinal=attempt_ordinal,
        expected_sha256=expected_sha256,
    )
    root = _artifact_root().resolve()
    current = root
    directories = [root]
    for part in path.parent.relative_to(root).parts:
        current = current / part
        directories.append(current)
    for directory in directories:
        try:
            directory_mode = stat.S_IMODE(directory.stat().st_mode)
        except OSError as error:
            raise StructuredRawArtifactError(
                f"Cannot inspect raw artifact directory {directory}: {error}"
            ) from error
        if directory.is_symlink() or directory_mode & 0o077:
            raise StructuredRawArtifactError(
                f"Raw artifact directory has non-private permissions: {directory}"
            )
    if path.is_symlink():
        raise StructuredRawArtifactError("Raw artifact path is a symbolic link.")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError as error:
        raise StructuredRawArtifactError(
            f"Selected raw artifact is missing: {artifact_ref}"
        ) from error
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Cannot inspect selected raw artifact {artifact_ref}: {error}"
        ) from error
    if mode & 0o077:
        raise StructuredRawArtifactError(
            f"Selected raw artifact has non-private permissions: {oct(mode)}"
        )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, os.O_RDONLY | nofollow)
        with os.fdopen(fd, "rb") as handle:
            raw_bytes = handle.read()
    except OSError as error:
        raise StructuredRawArtifactError(
            f"Cannot read selected raw artifact {artifact_ref}: {error}"
        ) from error
    observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if observed_sha256 != expected_sha256:
        raise StructuredRawArtifactError(
            "Selected raw artifact SHA-256 does not match its attempt receipt."
        )
    return raw_bytes
