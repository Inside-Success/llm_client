"""Authority-drift reconciliation storage and validation.

This module keeps authority drift machine-visible without requiring opportunistic
edits to separately claimed authority surfaces. The first implementation slice
targets indexed authority surfaces such as plan indexes, and schema v2 extends
that surface with a bounded recursive documentation spine used for dogfooding.
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import fnmatch
from pathlib import Path
import re
import uuid
from typing import Any

import yaml  # type: ignore[import-untyped]

from enforced_planning import coordination_claims
from enforced_planning.worktree_paths import resolve_canonical_repo_root


DEFAULT_DOC_AUTHORITY_CONFIG = Path("scripts/doc_authority.yaml")
AUTHORITY_OBLIGATIONS_DIR = Path.home() / ".claude" / "coordination" / "authority_obligations"
STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(.+?)(?:\n|$)")
PLAN_NUMBER_RE = re.compile(r"^(\d+)_")


@dataclass(frozen=True)
class AuthorityRule:
    """One configured indexed authority rule for a governed repo."""

    concern: str
    kind: str
    authority_surface: str
    source_glob: str
    resolution_mode: str


@dataclass(frozen=True)
class RequiredContextEntry:
    """One additional mandatory read attached to a doc-spine node."""

    path: str
    reason: str
    when: str | None = None


@dataclass(frozen=True)
class AuthorityDocEntry:
    """One authority-bearing document in the recursive documentation spine."""

    path: str
    authority: str
    doc_status: str
    concerns: tuple[str, ...]
    role: str
    primary_parent: str | None
    governed_by: tuple[str, ...] = ()
    required_context: tuple[RequiredContextEntry, ...] = ()


@dataclass(frozen=True)
class CodeSurfaceEntry:
    """One bounded code-surface mapping into the doc spine."""

    paths: tuple[str, ...]
    primary_spec: str


@dataclass(frozen=True)
class RoleBudget:
    """Configured size budget for one document role."""

    max_words: int | None = None
    summary_max_words: int | None = None


@dataclass(frozen=True)
class DocSpineConfig:
    """Repo-level recursive documentation-spine settings."""

    root_doc: str
    required_concerns: tuple[str, ...]
    max_required_read_docs: int | None = None
    max_required_read_words: int | None = None


@dataclass(frozen=True)
class DocSpineContext:
    """Resolved doc-spine closure for one managed code surface."""

    file_path: str
    matched_surface_paths: tuple[str, ...]
    primary_spec: str
    ancestor_chain: tuple[str, ...]
    governed_by: tuple[str, ...]
    required_context: tuple[RequiredContextEntry, ...]
    required_reads: tuple[str, ...]
    total_words: int


@dataclass(frozen=True)
class DocAuthorityConfig:
    """Parsed documentation-authority config for one repo."""

    schema_version: int
    indexed_authority_surfaces: tuple[AuthorityRule, ...]
    doc_spine: DocSpineConfig | None = None
    role_budgets: dict[str, RoleBudget] = field(default_factory=dict)
    docs: tuple[AuthorityDocEntry, ...] = ()
    code_surfaces: tuple[CodeSurfaceEntry, ...] = ()
    config_path: str | None = None


@dataclass(frozen=True)
class AuthorityObligation:
    """One unresolved or resolved reconciliation obligation."""

    obligation_id: str
    project: str
    concern: str
    authority_surface: str
    artifact_path: str
    required_action: str
    created_by_agent: str
    created_by_scope: str
    plan_ref: str | None
    owner_scope: str | None
    notes: str | None
    status: str
    created_at: str
    resolved_at: str | None
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-safe payload."""

        payload = asdict(self)
        payload.pop("source_file", None)
        return payload


@dataclass(frozen=True)
class AuthorityIssue:
    """One validation finding for doc-authority drift."""

    code: str
    severity: str
    concern: str
    authority_surface: str
    artifact_path: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe issue payload."""

        return asdict(self)


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path for overlap checks."""

    normalized = path.replace("\\", "/").strip()
    normalized = normalized.lstrip("./")
    return str(Path(normalized).as_posix())


def _paths_overlap(left: str, right: str) -> bool:
    """Return whether two repo-relative paths overlap."""

    left_norm = _normalize_repo_path(left)
    right_norm = _normalize_repo_path(right)
    return (
        left_norm == right_norm
        or left_norm.startswith(f"{right_norm}/")
        or right_norm.startswith(f"{left_norm}/")
    )


def _path_matches(pattern: str, candidate: str) -> bool:
    """Return whether one configured code-surface path matches a candidate."""

    normalized_pattern = _normalize_repo_path(pattern)
    normalized_candidate = _normalize_repo_path(candidate)
    if any(token in normalized_pattern for token in ("*", "?", "[")):
        return fnmatch.fnmatch(normalized_candidate, normalized_pattern)
    return _paths_overlap(normalized_pattern, normalized_candidate)


def _parse_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML mapping from disk."""

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def _severity_rank(value: str) -> int:
    """Return deterministic severity sorting order."""

    return {"info": 0, "warn": 1, "fail": 2}.get(value, 2)


def _parse_plan_doc_status(plan_path: Path) -> tuple[str, str] | None:
    """Return one plan number plus normalized status emoji."""

    match = PLAN_NUMBER_RE.match(plan_path.name)
    if not match:
        return None
    plan_number = str(int(match.group(1)))
    status_match = STATUS_RE.search(plan_path.read_text(encoding="utf-8"))
    if not status_match:
        return None
    raw_status = status_match.group(1).strip()
    for emoji in ("✅", "🚧", "📋", "⏸️", "❌"):
        if emoji in raw_status:
            return plan_number, emoji
    lowered = raw_status.lower()
    if "complete" in lowered:
        return plan_number, "✅"
    if "progress" in lowered:
        return plan_number, "🚧"
    if "planned" in lowered:
        return plan_number, "📋"
    if "blocked" in lowered:
        return plan_number, "⏸️"
    if "needs plan" in lowered:
        return plan_number, "❌"
    return plan_number, raw_status


def _parse_plan_index(index_path: Path) -> dict[str, str]:
    """Return plan-number to status-emoji mapping from the plan index table."""

    statuses: dict[str, str] = {}
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) < 4:
            continue
        plan_text = parts[0]
        if not plan_text.isdigit():
            continue
        status_cell = parts[3]
        for emoji in ("✅", "🚧", "📋", "⏸️", "❌"):
            if emoji in status_cell:
                statuses[plan_text] = emoji
                break
    return statuses


def _repo_project_name(repo_root: Path) -> str:
    """Return the canonical project name for a repo or worktree root."""

    return resolve_canonical_repo_root(repo_root).name


def _resolve_config_path(repo_root: Path, config_path: Path | None = None) -> Path:
    """Resolve the effective doc-authority config path for a repo or worktree."""

    canonical_repo_root = resolve_canonical_repo_root(repo_root)
    if config_path is not None:
        return config_path.expanduser().resolve()
    local_config_path = repo_root / DEFAULT_DOC_AUTHORITY_CONFIG
    canonical_config_path = canonical_repo_root / DEFAULT_DOC_AUTHORITY_CONFIG
    return local_config_path if local_config_path.exists() else canonical_config_path


def _require_nonempty_str(value: Any, *, field_name: str, config_path: Path) -> str:
    """Return one required non-empty string field from config."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid `{field_name}` in {config_path}")
    return value.strip()


def _coerce_int(value: Any, *, field_name: str, config_path: Path) -> int | None:
    """Parse one optional integer field from config."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid `{field_name}` in {config_path}")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Invalid `{field_name}` in {config_path}") from exc


def _coerce_str_tuple(value: Any, *, field_name: str, config_path: Path) -> tuple[str, ...]:
    """Normalize one string-or-list-of-strings field into a tuple."""

    if value in (None, ""):
        return ()
    if isinstance(value, list):
        result = []
        for item in value:
            result.append(_require_nonempty_str(item, field_name=field_name, config_path=config_path))
        return tuple(result)
    return (_require_nonempty_str(value, field_name=field_name, config_path=config_path),)


def _parse_required_context_entries(raw_entries: Any, *, config_path: Path) -> tuple[RequiredContextEntry, ...]:
    """Parse required-context items from config."""

    if raw_entries in (None, ""):
        return ()
    if not isinstance(raw_entries, list):
        raise ValueError(f"Invalid `required_context` in {config_path}")
    entries: list[RequiredContextEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid `required_context` in {config_path}")
        path = _normalize_repo_path(_require_nonempty_str(item.get("path"), field_name="required_context.path", config_path=config_path))
        reason = _require_nonempty_str(item.get("reason"), field_name="required_context.reason", config_path=config_path)
        when_raw = item.get("when")
        when = None
        if when_raw is not None:
            when = _require_nonempty_str(when_raw, field_name="required_context.when", config_path=config_path)
        entries.append(RequiredContextEntry(path=path, reason=reason, when=when))
    return tuple(entries)


def _parse_indexed_authority_rules(payload: dict[str, Any], *, config_path: Path) -> tuple[AuthorityRule, ...]:
    """Parse indexed authority rules from config."""

    rules: list[AuthorityRule] = []
    for item in payload.get("indexed_authority_surfaces", []) or []:
        if not isinstance(item, dict):
            continue
        rules.append(
            AuthorityRule(
                concern=_require_nonempty_str(item.get("concern"), field_name="indexed_authority_surfaces.concern", config_path=config_path),
                kind=_require_nonempty_str(item.get("kind"), field_name="indexed_authority_surfaces.kind", config_path=config_path),
                authority_surface=_normalize_repo_path(_require_nonempty_str(item.get("authority_surface"), field_name="indexed_authority_surfaces.authority_surface", config_path=config_path)),
                source_glob=_require_nonempty_str(item.get("source_glob"), field_name="indexed_authority_surfaces.source_glob", config_path=config_path),
                resolution_mode=_require_nonempty_str(item.get("resolution_mode", "manual"), field_name="indexed_authority_surfaces.resolution_mode", config_path=config_path),
            )
        )
    return tuple(rules)


def _parse_doc_spine(payload: dict[str, Any], *, config_path: Path) -> DocSpineConfig | None:
    """Parse repo-level doc-spine settings from config."""

    raw = payload.get("doc_spine")
    if raw in (None, ""):
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid `doc_spine` in {config_path}")
    return DocSpineConfig(
        root_doc=_normalize_repo_path(_require_nonempty_str(raw.get("root_doc"), field_name="doc_spine.root_doc", config_path=config_path)),
        required_concerns=_coerce_str_tuple(raw.get("required_concerns"), field_name="doc_spine.required_concerns", config_path=config_path),
        max_required_read_docs=_coerce_int(raw.get("max_required_read_docs"), field_name="doc_spine.max_required_read_docs", config_path=config_path),
        max_required_read_words=_coerce_int(raw.get("max_required_read_words"), field_name="doc_spine.max_required_read_words", config_path=config_path),
    )


def _parse_role_budgets(payload: dict[str, Any], *, config_path: Path) -> dict[str, RoleBudget]:
    """Parse role budgets from config."""

    raw = payload.get("role_budgets") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid `role_budgets` in {config_path}")
    budgets: dict[str, RoleBudget] = {}
    for role_name, item in raw.items():
        role = _require_nonempty_str(role_name, field_name="role_budgets.role", config_path=config_path)
        if not isinstance(item, dict):
            raise ValueError(f"Invalid `role_budgets.{role}` in {config_path}")
        budgets[role] = RoleBudget(
            max_words=_coerce_int(item.get("max_words"), field_name=f"role_budgets.{role}.max_words", config_path=config_path),
            summary_max_words=_coerce_int(item.get("summary_max_words"), field_name=f"role_budgets.{role}.summary_max_words", config_path=config_path),
        )
    return budgets


def _parse_docs(payload: dict[str, Any], *, config_path: Path) -> tuple[AuthorityDocEntry, ...]:
    """Parse authority-bearing docs from config."""

    raw_docs = payload.get("docs") or []
    if not isinstance(raw_docs, list):
        raise ValueError(f"Invalid `docs` in {config_path}")
    docs: list[AuthorityDocEntry] = []
    for item in raw_docs:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid `docs` entry in {config_path}")
        primary_parent_raw = item.get("primary_parent")
        primary_parent = None
        if primary_parent_raw is not None:
            primary_parent = _normalize_repo_path(
                _require_nonempty_str(primary_parent_raw, field_name="docs.primary_parent", config_path=config_path)
            )
        docs.append(
            AuthorityDocEntry(
                path=_normalize_repo_path(_require_nonempty_str(item.get("path"), field_name="docs.path", config_path=config_path)),
                authority=_require_nonempty_str(item.get("authority", "canonical"), field_name="docs.authority", config_path=config_path),
                doc_status=_require_nonempty_str(item.get("doc_status", "active"), field_name="docs.doc_status", config_path=config_path),
                concerns=_coerce_str_tuple(item.get("concerns"), field_name="docs.concerns", config_path=config_path),
                role=_require_nonempty_str(item.get("role"), field_name="docs.role", config_path=config_path),
                primary_parent=primary_parent,
                governed_by=tuple(_normalize_repo_path(path) for path in _coerce_str_tuple(item.get("governed_by"), field_name="docs.governed_by", config_path=config_path)),
                required_context=_parse_required_context_entries(item.get("required_context"), config_path=config_path),
            )
        )
    return tuple(docs)


def _parse_code_surfaces(payload: dict[str, Any], *, config_path: Path) -> tuple[CodeSurfaceEntry, ...]:
    """Parse bounded code-surface mappings from config."""

    raw_surfaces = payload.get("code_surfaces") or []
    if not isinstance(raw_surfaces, list):
        raise ValueError(f"Invalid `code_surfaces` in {config_path}")
    code_surfaces: list[CodeSurfaceEntry] = []
    for item in raw_surfaces:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid `code_surfaces` entry in {config_path}")
        paths = tuple(_normalize_repo_path(path) for path in _coerce_str_tuple(item.get("paths"), field_name="code_surfaces.paths", config_path=config_path))
        if not paths:
            raise ValueError(f"Invalid `code_surfaces.paths` in {config_path}")
        code_surfaces.append(
            CodeSurfaceEntry(
                paths=paths,
                primary_spec=_normalize_repo_path(_require_nonempty_str(item.get("primary_spec"), field_name="code_surfaces.primary_spec", config_path=config_path)),
            )
        )
    return tuple(code_surfaces)


def load_doc_authority_config(repo_root: Path, *, config_path: Path | None = None) -> DocAuthorityConfig:
    """Load the full doc-authority config for one repo."""

    resolved_config_path = _resolve_config_path(repo_root, config_path=config_path)
    payload = _parse_yaml_mapping(resolved_config_path)
    schema_version = _coerce_int(payload.get("schema_version", 1), field_name="schema_version", config_path=resolved_config_path)
    if schema_version is None:
        schema_version = 1
    return DocAuthorityConfig(
        schema_version=schema_version,
        indexed_authority_surfaces=_parse_indexed_authority_rules(payload, config_path=resolved_config_path),
        doc_spine=_parse_doc_spine(payload, config_path=resolved_config_path),
        role_budgets=_parse_role_budgets(payload, config_path=resolved_config_path),
        docs=_parse_docs(payload, config_path=resolved_config_path),
        code_surfaces=_parse_code_surfaces(payload, config_path=resolved_config_path),
        config_path=str(resolved_config_path),
    )


def load_authority_rules(repo_root: Path, *, config_path: Path | None = None) -> list[AuthorityRule]:
    """Load indexed doc-authority rules for one repo."""

    return list(load_doc_authority_config(repo_root, config_path=config_path).indexed_authority_surfaces)


def _doc_map(config: DocAuthorityConfig) -> dict[str, AuthorityDocEntry]:
    """Return path to doc-entry mapping for one config."""

    return {entry.path: entry for entry in config.docs}


def _resolve_repo_file(repo_root: Path, relative_path: str) -> Path:
    """Resolve one repo-relative path from the active repo or worktree root."""

    return repo_root.resolve() / _normalize_repo_path(relative_path)


def _word_count(path: Path) -> int:
    """Return a simple whitespace-based word count for one file."""

    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").split())


def _dedupe_paths(paths: list[str]) -> tuple[str, ...]:
    """Return a stable deduplicated path tuple."""

    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        normalized = _normalize_repo_path(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _dedupe_required_context(entries: list[RequiredContextEntry]) -> tuple[RequiredContextEntry, ...]:
    """Return stable deduplicated required-context entries by path."""

    seen: set[str] = set()
    ordered: list[RequiredContextEntry] = []
    for entry in entries:
        if entry.path in seen:
            continue
        seen.add(entry.path)
        ordered.append(entry)
    return tuple(ordered)


def _build_doc_chain(config: DocAuthorityConfig, start_path: str) -> list[AuthorityDocEntry]:
    """Resolve one doc plus its ancestor chain."""

    docs = _doc_map(config)
    current_path = _normalize_repo_path(start_path)
    chain: list[AuthorityDocEntry] = []
    seen: set[str] = set()
    while current_path:
        if current_path in seen:
            raise ValueError(f"Cycle detected while resolving doc spine for {start_path}")
        seen.add(current_path)
        entry = docs.get(current_path)
        if entry is None:
            raise ValueError(f"Unknown doc-spine path referenced from {start_path}: {current_path}")
        chain.append(entry)
        if entry.primary_parent is None:
            break
        current_path = entry.primary_parent
    return chain


def _match_code_surface(config: DocAuthorityConfig, file_path: str) -> CodeSurfaceEntry | None:
    """Return the matching bounded code surface for one file path, if any."""

    normalized = _normalize_repo_path(file_path)
    for surface in config.code_surfaces:
        if any(_path_matches(path, normalized) for path in surface.paths):
            return surface
    return None


def get_doc_spine_context(
    repo_root: Path,
    file_path: str,
    *,
    config_path: Path | None = None,
    config: DocAuthorityConfig | None = None,
) -> DocSpineContext | None:
    """Return the resolved doc-spine closure for one managed file, if any."""

    loaded_config = config or load_doc_authority_config(repo_root, config_path=config_path)
    if loaded_config.doc_spine is None:
        return None
    surface = _match_code_surface(loaded_config, file_path)
    if surface is None:
        return None

    chain = _build_doc_chain(loaded_config, surface.primary_spec)
    ancestor_chain = tuple(entry.path for entry in chain[1:])

    governed_by: list[str] = []
    required_context_entries: list[RequiredContextEntry] = []
    required_reads: list[str] = [surface.primary_spec]
    required_reads.extend(ancestor_chain)
    for entry in chain:
        governed_by.extend(entry.governed_by)
        required_context_entries.extend(entry.required_context)
    required_context = _dedupe_required_context(required_context_entries)
    required_reads.extend(governed_by)
    required_reads.extend(entry.path for entry in required_context)
    deduped_reads = _dedupe_paths(required_reads)

    repo_root_resolved = repo_root.resolve()
    total_words = sum(_word_count(repo_root_resolved / path) for path in deduped_reads)
    return DocSpineContext(
        file_path=_normalize_repo_path(file_path),
        matched_surface_paths=surface.paths,
        primary_spec=surface.primary_spec,
        ancestor_chain=ancestor_chain,
        governed_by=_dedupe_paths(governed_by),
        required_context=required_context,
        required_reads=deduped_reads,
        total_words=total_words,
    )


def list_obligations(
    *,
    project: str | None = None,
    concern: str | None = None,
    status: str | None = None,
) -> list[AuthorityObligation]:
    """Return authority obligations filtered by project/concern/status."""

    if not AUTHORITY_OBLIGATIONS_DIR.exists():
        return []
    obligations: list[AuthorityObligation] = []
    for obligation_file in sorted(AUTHORITY_OBLIGATIONS_DIR.glob("*.yaml")):
        payload = _parse_yaml_mapping(obligation_file)
        record = AuthorityObligation(
            obligation_id=str(payload.get("obligation_id", "")).strip(),
            project=str(payload.get("project", "")).strip(),
            concern=str(payload.get("concern", "")).strip(),
            authority_surface=_normalize_repo_path(str(payload.get("authority_surface", "")).strip()),
            artifact_path=_normalize_repo_path(str(payload.get("artifact_path", "")).strip()),
            required_action=str(payload.get("required_action", "")).strip(),
            created_by_agent=str(payload.get("created_by_agent", "")).strip(),
            created_by_scope=str(payload.get("created_by_scope", "")).strip(),
            plan_ref=str(payload.get("plan_ref", "")).strip() or None,
            owner_scope=str(payload.get("owner_scope", "")).strip() or None,
            notes=str(payload.get("notes", "")).strip() or None,
            status=str(payload.get("status", "open")).strip() or "open",
            created_at=str(payload.get("created_at", "")).strip(),
            resolved_at=str(payload.get("resolved_at", "")).strip() or None,
            source_file=str(obligation_file),
        )
        if not record.obligation_id:
            continue
        if project and record.project != project:
            continue
        if concern and record.concern != concern:
            continue
        if status and record.status != status:
            continue
        obligations.append(record)
    return obligations


def record_obligation(
    *,
    project: str,
    concern: str,
    authority_surface: str,
    artifact_path: str,
    required_action: str,
    created_by_agent: str,
    created_by_scope: str,
    plan_ref: str | None = None,
    owner_scope: str | None = None,
    notes: str | None = None,
) -> AuthorityObligation:
    """Create or return one open authority reconciliation obligation."""

    authority_surface_norm = _normalize_repo_path(authority_surface)
    artifact_path_norm = _normalize_repo_path(artifact_path)
    for existing in list_obligations(project=project, concern=concern, status="open"):
        if (
            existing.authority_surface == authority_surface_norm
            and existing.artifact_path == artifact_path_norm
        ):
            return existing

    now = datetime.now(timezone.utc).isoformat()
    obligation_id = f"{project}-{uuid.uuid4().hex[:12]}"
    record = AuthorityObligation(
        obligation_id=obligation_id,
        project=project,
        concern=concern,
        authority_surface=authority_surface_norm,
        artifact_path=artifact_path_norm,
        required_action=required_action.strip(),
        created_by_agent=created_by_agent.strip(),
        created_by_scope=created_by_scope.strip(),
        plan_ref=plan_ref.strip() if isinstance(plan_ref, str) and plan_ref.strip() else None,
        owner_scope=owner_scope.strip() if isinstance(owner_scope, str) and owner_scope.strip() else None,
        notes=notes.strip() if isinstance(notes, str) and notes.strip() else None,
        status="open",
        created_at=now,
        resolved_at=None,
    )
    AUTHORITY_OBLIGATIONS_DIR.mkdir(parents=True, exist_ok=True)
    obligation_path = AUTHORITY_OBLIGATIONS_DIR / f"{obligation_id}.yaml"
    obligation_path.write_text(
        yaml.safe_dump(record.to_dict(), default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return AuthorityObligation(**{**record.to_dict(), "source_file": str(obligation_path)})


def resolve_obligation(*, obligation_id: str, notes: str | None = None) -> AuthorityObligation:
    """Mark one obligation resolved and return the updated record."""

    obligation_path = AUTHORITY_OBLIGATIONS_DIR / f"{obligation_id}.yaml"
    if not obligation_path.exists():
        raise ValueError(f"Unknown authority obligation: {obligation_id}")
    payload = _parse_yaml_mapping(obligation_path)
    payload["status"] = "resolved"
    payload["resolved_at"] = datetime.now(timezone.utc).isoformat()
    if notes:
        payload["notes"] = notes
    obligation_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return AuthorityObligation(**{**payload, "source_file": str(obligation_path)})


def _owner_claims_for_surface(project: str, authority_surface: str) -> list[coordination_claims.ClaimRecord]:
    """Return live write claims that own one authority surface."""

    claims = coordination_claims.check_claims(project)
    owners: list[coordination_claims.ClaimRecord] = []
    for claim in claims:
        if claim.claim_type != "write":
            continue
        if any(_paths_overlap(authority_surface, write_path) for write_path in claim.write_paths):
            owners.append(claim)
    return owners


def _matching_open_obligations(
    *,
    project: str,
    concern: str,
    authority_surface: str,
    artifact_path: str,
) -> list[AuthorityObligation]:
    """Return open obligations for one concrete drift item."""

    matches: list[AuthorityObligation] = []
    for obligation in list_obligations(project=project, concern=concern, status="open"):
        if (
            obligation.authority_surface == _normalize_repo_path(authority_surface)
            and obligation.artifact_path == _normalize_repo_path(artifact_path)
        ):
            matches.append(obligation)
    return matches


def _issue(
    *,
    code: str,
    severity: str,
    concern: str,
    authority_surface: str,
    artifact_path: str,
    message: str,
    evidence: dict[str, Any],
) -> AuthorityIssue:
    """Build one authority validation issue."""

    return AuthorityIssue(
        code=code,
        severity=severity,
        concern=concern,
        authority_surface=_normalize_repo_path(authority_surface),
        artifact_path=_normalize_repo_path(artifact_path),
        message=message,
        evidence=evidence,
    )


def _validate_plan_index_rule(repo_root: Path, rule: AuthorityRule) -> list[AuthorityIssue]:
    """Validate one indexed plan authority surface."""

    canonical_repo_root = resolve_canonical_repo_root(repo_root)
    authority_surface_path = canonical_repo_root / rule.authority_surface
    if not authority_surface_path.exists():
        raise ValueError(f"Authority surface does not exist: {authority_surface_path}")
    index_statuses = _parse_plan_index(authority_surface_path)
    issues: list[AuthorityIssue] = []
    project = _repo_project_name(canonical_repo_root)
    for plan_path in sorted(canonical_repo_root.glob(rule.source_glob)):
        parsed = _parse_plan_doc_status(plan_path)
        if parsed is None:
            continue
        plan_number, file_status = parsed
        artifact_path = _normalize_repo_path(str(plan_path.relative_to(canonical_repo_root)))
        issue_code: str | None = None
        issue_message: str | None = None
        if plan_number not in index_statuses:
            issue_code = "authority_surface_missing_artifact"
            issue_message = f"{rule.authority_surface} does not index {artifact_path}."
        elif index_statuses[plan_number] != file_status:
            issue_code = "authority_surface_status_mismatch"
            issue_message = (
                f"{rule.authority_surface} reports Plan #{plan_number} as {index_statuses[plan_number]} "
                f"but {artifact_path} is {file_status}."
            )
        if issue_code is None or issue_message is None:
            continue

        owners = _owner_claims_for_surface(project, rule.authority_surface)
        obligations = _matching_open_obligations(
            project=project,
            concern=rule.concern,
            authority_surface=rule.authority_surface,
            artifact_path=artifact_path,
        )
        evidence = {
            "plan_number": plan_number,
            "authority_surface": rule.authority_surface,
            "artifact_path": artifact_path,
            "owner_scopes": [claim.scope for claim in owners],
            "obligation_ids": [obligation.obligation_id for obligation in obligations],
            "resolution_mode": rule.resolution_mode,
        }
        if rule.resolution_mode == "generated":
            issues.append(
                _issue(
                    code="generated_authority_surface_requires_regeneration",
                    severity="fail",
                    concern=rule.concern,
                    authority_surface=rule.authority_surface,
                    artifact_path=artifact_path,
                    message=(
                        f"{issue_message} This surface is configured as generated, so regenerate it instead of leaving drift."
                    ),
                    evidence=evidence,
                )
            )
            continue
        if obligations:
            issues.append(
                _issue(
                    code="recorded_reconciliation_obligation",
                    severity="info",
                    concern=rule.concern,
                    authority_surface=rule.authority_surface,
                    artifact_path=artifact_path,
                    message=(
                        f"{issue_message} Drift is recorded as reconciliation obligation "
                        f"{obligations[0].obligation_id}."
                    ),
                    evidence=evidence,
                )
            )
            continue
        if owners:
            issues.append(
                _issue(
                    code="missing_reconciliation_obligation",
                    severity="fail",
                    concern=rule.concern,
                    authority_surface=rule.authority_surface,
                    artifact_path=artifact_path,
                    message=(
                        f"{issue_message} Authority surface owner(s) exist, so the landing lane "
                        "must record a reconciliation obligation instead of leaving silent drift."
                    ),
                    evidence=evidence,
                )
            )
            continue
        issues.append(
            _issue(
                code="unowned_authority_drift",
                severity="fail",
                concern=rule.concern,
                authority_surface=rule.authority_surface,
                artifact_path=artifact_path,
                message=(
                    f"{issue_message} No active claim owns {rule.authority_surface}, so the drift is unowned."
                ),
                evidence=evidence,
            )
        )
    return issues


def _validate_doc_spine(repo_root: Path, config: DocAuthorityConfig) -> list[AuthorityIssue]:
    """Validate the bounded recursive doc spine for one repo."""

    if config.doc_spine is None:
        return []

    repo_root_resolved = repo_root.resolve()
    docs = _doc_map(config)
    root_doc = config.doc_spine.root_doc
    issues: list[AuthorityIssue] = []

    if root_doc not in docs:
        issues.append(
            _issue(
                code="root_doc_missing",
                severity="fail",
                concern="execution_brief",
                authority_surface=root_doc,
                artifact_path=root_doc,
                message=f"Configured root doc `{root_doc}` is not declared in `docs`.",
                evidence={"root_doc": root_doc},
            )
        )
        return issues

    concern_to_docs: dict[str, list[AuthorityDocEntry]] = {}
    for entry in config.docs:
        doc_path = repo_root_resolved / entry.path
        if not doc_path.exists():
            issues.append(
                _issue(
                    code="authority_doc_missing",
                    severity="fail",
                    concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                    authority_surface=root_doc,
                    artifact_path=entry.path,
                    message=f"Authority doc `{entry.path}` does not exist.",
                    evidence={"doc": entry.path},
                )
            )

        if entry.path == root_doc and entry.primary_parent is not None:
            issues.append(
                _issue(
                    code="root_doc_has_parent",
                    severity="fail",
                    concern="execution_brief",
                    authority_surface=root_doc,
                    artifact_path=entry.path,
                    message=f"Root doc `{entry.path}` must not declare `primary_parent`.",
                    evidence={"primary_parent": entry.primary_parent},
                )
            )
        if entry.path != root_doc and entry.primary_parent is None:
            issues.append(
                _issue(
                    code="doc_spine_orphan_doc",
                    severity="fail",
                    concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                    authority_surface=root_doc,
                    artifact_path=entry.path,
                    message=f"Non-root authority doc `{entry.path}` must declare `primary_parent`.",
                    evidence={"doc": entry.path},
                )
            )
        if entry.primary_parent and entry.primary_parent not in docs:
            issues.append(
                _issue(
                    code="doc_spine_missing_primary_parent",
                    severity="fail",
                    concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                    authority_surface=root_doc,
                    artifact_path=entry.path,
                    message=(
                        f"Authority doc `{entry.path}` references unknown primary parent `{entry.primary_parent}`."
                    ),
                    evidence={"primary_parent": entry.primary_parent},
                )
            )

        for concern in entry.concerns:
            concern_to_docs.setdefault(concern, []).append(entry)

        for governed_path in entry.governed_by:
            if not _resolve_repo_file(repo_root_resolved, governed_path).exists():
                issues.append(
                    _issue(
                        code="governed_by_path_missing",
                        severity="fail",
                        concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                        authority_surface=root_doc,
                        artifact_path=entry.path,
                        message=(
                            f"Authority doc `{entry.path}` references missing governed-by path `{governed_path}`."
                        ),
                        evidence={"governed_by": governed_path},
                    )
                )

        for required_entry in entry.required_context:
            if not required_entry.reason.strip():
                issues.append(
                    _issue(
                        code="required_context_missing_reason",
                        severity="fail",
                        concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                        authority_surface=root_doc,
                        artifact_path=entry.path,
                        message=(
                            f"Authority doc `{entry.path}` has `required_context` without a reason."
                        ),
                        evidence={"required_context": required_entry.path},
                    )
                )
            if not _resolve_repo_file(repo_root_resolved, required_entry.path).exists():
                issues.append(
                    _issue(
                        code="required_context_path_missing",
                        severity="fail",
                        concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                        authority_surface=root_doc,
                        artifact_path=entry.path,
                        message=(
                            f"Authority doc `{entry.path}` references missing required-context path `{required_entry.path}`."
                        ),
                        evidence={"required_context": required_entry.path},
                    )
                )

    for concern in config.doc_spine.required_concerns:
        if not concern_to_docs.get(concern):
            issues.append(
                _issue(
                    code="required_concern_missing",
                    severity="fail",
                    concern=concern,
                    authority_surface=root_doc,
                    artifact_path=root_doc,
                    message=f"Required concern `{concern}` has no active canonical doc in the doc spine.",
                    evidence={"required_concern": concern},
                )
            )

    for concern, entries in concern_to_docs.items():
        if len(entries) <= 1:
            continue
        for entry in entries[1:]:
            issues.append(
                _issue(
                    code="duplicate_active_canonical_concern",
                    severity="fail",
                    concern=concern,
                    authority_surface=root_doc,
                    artifact_path=entry.path,
                    message=f"Concern `{concern}` is declared by more than one active canonical doc.",
                    evidence={"concern": concern, "paths": [candidate.path for candidate in entries]},
                )
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(path: str) -> None:
        if path in visited:
            return
        if path in visiting:
            issues.append(
                _issue(
                    code="doc_spine_cycle",
                    severity="fail",
                    concern="doc-spine",
                    authority_surface=root_doc,
                    artifact_path=path,
                    message=f"Primary-parent cycle detected at `{path}`.",
                    evidence={"path": path},
                )
            )
            return
        visiting.add(path)
        parent = docs[path].primary_parent
        if parent and parent in docs:
            walk(parent)
        visiting.remove(path)
        visited.add(path)

    for path in docs:
        walk(path)

    for role, budget in config.role_budgets.items():
        if budget.max_words is None:
            continue
        for entry in config.docs:
            if entry.role != role:
                continue
            word_count = _word_count(repo_root_resolved / entry.path)
            if word_count > budget.max_words:
                issues.append(
                    _issue(
                        code="role_budget_exceeded",
                        severity="warn",
                        concern=(entry.concerns[0] if entry.concerns else "doc-spine"),
                        authority_surface=root_doc,
                        artifact_path=entry.path,
                        message=(
                            f"Authority doc `{entry.path}` exceeds the `{role}` budget "
                            f"({word_count} > {budget.max_words} words)."
                        ),
                        evidence={"role": role, "word_count": word_count, "budget": budget.max_words},
                    )
                )

    for surface in config.code_surfaces:
        if surface.primary_spec not in docs:
            issues.append(
                _issue(
                    code="code_surface_primary_spec_missing",
                    severity="fail",
                    concern="doc-spine",
                    authority_surface=root_doc,
                    artifact_path=surface.paths[0],
                    message=(
                        f"Code surface `{surface.paths[0]}` references unknown primary spec `{surface.primary_spec}`."
                    ),
                    evidence={"paths": list(surface.paths), "primary_spec": surface.primary_spec},
                )
            )
            continue
        context = get_doc_spine_context(repo_root_resolved, surface.paths[0], config=config)
        if context is None:
            continue
        if (
            config.doc_spine.max_required_read_docs is not None
            and len(context.required_reads) > config.doc_spine.max_required_read_docs
        ):
            issues.append(
                _issue(
                    code="required_read_budget_exceeded",
                    severity="warn",
                    concern="doc-spine",
                    authority_surface=root_doc,
                    artifact_path=surface.paths[0],
                    message=(
                        f"Required-read doc budget exceeded for `{surface.paths[0]}` "
                        f"({len(context.required_reads)} > {config.doc_spine.max_required_read_docs})."
                    ),
                    evidence={
                        "paths": list(surface.paths),
                        "required_reads": list(context.required_reads),
                        "max_required_read_docs": config.doc_spine.max_required_read_docs,
                    },
                )
            )
        if (
            config.doc_spine.max_required_read_words is not None
            and context.total_words > config.doc_spine.max_required_read_words
        ):
            issues.append(
                _issue(
                    code="required_read_budget_exceeded",
                    severity="warn",
                    concern="doc-spine",
                    authority_surface=root_doc,
                    artifact_path=surface.paths[0],
                    message=(
                        f"Required-read word budget exceeded for `{surface.paths[0]}` "
                        f"({context.total_words} > {config.doc_spine.max_required_read_words})."
                    ),
                    evidence={
                        "paths": list(surface.paths),
                        "required_reads": list(context.required_reads),
                        "total_words": context.total_words,
                        "max_required_read_words": config.doc_spine.max_required_read_words,
                    },
                )
            )

    return issues


def validate_doc_authority(
    repo_root: Path,
    *,
    config_path: Path | None = None,
) -> list[AuthorityIssue]:
    """Return sorted authority validation issues for one repo."""

    config = load_doc_authority_config(repo_root, config_path=config_path)
    issues: list[AuthorityIssue] = []
    for rule in config.indexed_authority_surfaces:
        if rule.kind == "plan_index":
            issues.extend(_validate_plan_index_rule(repo_root, rule))
            continue
        raise ValueError(f"Unsupported authority rule kind: {rule.kind}")
    issues.extend(_validate_doc_spine(repo_root, config))
    return sorted(
        issues,
        key=lambda item: (
            -_severity_rank(item.severity),
            item.concern,
            item.artifact_path,
        ),
    )


def unresolved_owned_obligations(claim: coordination_claims.ClaimRecord) -> list[AuthorityObligation]:
    """Return unresolved obligations against surfaces owned by one claim."""

    project = claim.primary_project()
    if not project or not claim.write_paths:
        return []
    obligations = list_obligations(project=project, status="open")
    matches: list[AuthorityObligation] = []
    for obligation in obligations:
        if any(_paths_overlap(obligation.authority_surface, write_path) for write_path in claim.write_paths):
            matches.append(obligation)
    return matches


def assert_no_unresolved_owned_obligations(claim: coordination_claims.ClaimRecord) -> None:
    """Fail loud when one lane owns an authority surface with open debt."""

    matches = unresolved_owned_obligations(claim)
    if not matches:
        return
    formatted = "; ".join(
        f"{item.concern}::{item.authority_surface} <- {item.artifact_path} ({item.obligation_id})"
        for item in matches
    )
    raise ValueError(
        "Cannot close this lane because it owns authority surfaces with unresolved "
        f"reconciliation obligations: {formatted}"
    )
