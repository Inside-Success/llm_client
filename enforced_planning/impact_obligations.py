"""Derive auditable reconciliation obligations from changed relationship nodes.

This module turns a concrete changed-file set plus maintenance-bearing graph
edges into deterministic obligations. It is intentionally report-only until a
consumer pilot measures false positives and disposition quality.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Literal, TypeAlias

import yaml  # type: ignore[import-untyped]

from enforced_planning.context_packet import ContextPacketError
from enforced_planning.context_packet import RelationshipSpec
from enforced_planning.context_packet import expand_selectors
from enforced_planning.context_packet import relationship_specs
from enforced_planning.context_packet import selector_path_matches
from enforced_planning.relationship_context import inventory_repository


DispositionStatus: TypeAlias = Literal["verified_unchanged", "superseded", "blocked"]
ObligationStatus: TypeAlias = Literal["updated", "verified_unchanged", "superseded", "unresolved", "blocked"]
PlanLifecycle: TypeAlias = Literal["active", "planned", "blocked", "completed", "superseded", "archived", "unknown"]


class ImpactObligationError(RuntimeError):
    """Report malformed change, revision, or disposition evidence."""


@dataclass(frozen=True)
class ReconciliationDisposition:
    """Record one reviewed resolution that cannot be inferred from changed files."""

    obligation_id: str
    status: DispositionStatus
    reason: str
    reviewed_revision: str
    successor: str | None = None


@dataclass(frozen=True)
class ImpactObligation:
    """Require one linked artifact to be reconciled after a source change."""

    obligation_id: str
    changed_path: str
    related_path: str
    related_symbol: str | None
    relation: str
    reason: str
    maintenance: str
    provenance: str
    related_lifecycle: str | None
    status: ObligationStatus
    disposition_reason: str | None
    successor: str | None


@dataclass(frozen=True)
class ImpactReport:
    """Summarize deterministic reconciliation state for one repository diff."""

    schema_version: int
    revision: str
    changed_paths: tuple[str, ...]
    obligation_count: int
    unresolved_count: int
    obligations: tuple[ImpactObligation, ...]
    diagnostics: tuple[str, ...]

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize a stable report for hooks, CI, and agents."""

        return json.dumps(
            asdict(self),
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ) + "\n"


def current_revision(repo_root: Path) -> str:
    """Return repository HEAD for provenance, not as a working-diff review token."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root.resolve()), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ImpactObligationError(f"cannot resolve repository revision: {exc}") from exc
    return result.stdout.strip()


def review_revision(repo_root: Path, *, base: str, staged: bool = False) -> str:
    """Fingerprint HEAD, comparison mode, base, and exact diff under review."""

    root = repo_root.resolve()
    command = ["git", "-C", str(root), "diff", "--binary"]
    if staged:
        command.append("--cached")
    command.append(base)
    try:
        diff = subprocess.run(command, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise ImpactObligationError(f"cannot fingerprint review diff against {base!r}: {detail or exc}") from exc
    payload = b"\0".join(
        (
            current_revision(root).encode("ascii"),
            base.encode("utf-8", errors="surrogateescape"),
            b"staged" if staged else b"working-tree",
            diff,
        )
    )
    return "review_" + hashlib.sha256(payload).hexdigest()


def changed_paths(repo_root: Path, *, base: str, staged: bool = False) -> tuple[str, ...]:
    """Return a NUL-safe changed path set from the requested Git comparison."""

    command = ["git", "-C", str(repo_root.resolve()), "diff", "--name-only", "-z"]
    if staged:
        command.append("--cached")
    command.append(base)
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise ImpactObligationError(f"cannot resolve changed paths against {base!r}: {detail or exc}") from exc
    return tuple(sorted(item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item))


def _obligation_id(changed_path: str, related_path: str, related_symbol: str | None, spec: RelationshipSpec) -> str:
    """Derive a stable obligation id from semantic edge identity, not line numbers."""

    payload = "\0".join(
        (
            changed_path,
            related_path,
            related_symbol or "",
            spec.relation,
            spec.maintenance,
            spec.provenance,
        )
    ).encode("utf-8", errors="surrogateescape")
    return "obl_" + hashlib.sha256(payload).hexdigest()[:20]


def load_dispositions(path: Path | None) -> tuple[ReconciliationDisposition, ...]:
    """Load and validate optional reviewed reconciliation dispositions."""

    if path is None or not path.exists():
        return ()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = loaded.get("dispositions", []) if isinstance(loaded, dict) else None
    if not isinstance(rows, list):
        raise ImpactObligationError("disposition file must contain a dispositions list")
    dispositions: list[ReconciliationDisposition] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ImpactObligationError(f"dispositions[{index}] must be a mapping")
        status = str(row.get("status", ""))
        if status not in {"verified_unchanged", "superseded", "blocked"}:
            raise ImpactObligationError(f"dispositions[{index}] has unsupported status {status!r}")
        reason = str(row.get("reason", "")).strip()
        revision = str(row.get("reviewed_revision", "")).strip()
        if not reason or not revision:
            raise ImpactObligationError(f"dispositions[{index}] requires reason and reviewed_revision")
        successor = str(row["successor"]).strip() if row.get("successor") else None
        if status == "superseded" and not successor:
            raise ImpactObligationError(f"dispositions[{index}] superseded status requires successor")
        dispositions.append(
            ReconciliationDisposition(
                obligation_id=str(row.get("obligation_id", "")).strip(),
                status=status,  # type: ignore[arg-type]
                reason=reason,
                reviewed_revision=revision,
                successor=successor,
            )
        )
    return tuple(dispositions)


def _apply_disposition(
    obligation_id: str,
    *,
    revision: str,
    disposition: ReconciliationDisposition | None,
    tracked_paths: set[str],
) -> tuple[ObligationStatus, str | None, str | None]:
    """Validate one reviewed disposition against current revision and inventory."""

    if disposition is None:
        return "unresolved", None, None
    if disposition.obligation_id != obligation_id:
        return "unresolved", None, None
    if disposition.reviewed_revision != revision:
        raise ImpactObligationError(
            f"disposition {obligation_id} reviewed {disposition.reviewed_revision}, expected current {revision}"
        )
    if disposition.status == "superseded":
        if disposition.successor not in tracked_paths:
            raise ImpactObligationError(
                f"disposition {obligation_id} successor is not Git-tracked: {disposition.successor}"
            )
        return "superseded", disposition.reason, disposition.successor
    if disposition.status == "blocked":
        return "blocked", disposition.reason, None
    return "verified_unchanged", disposition.reason, None


def plan_lifecycle(path: Path) -> PlanLifecycle:
    """Classify a plan's declared status without treating its filename as truth."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unknown"
    status = ""
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if stripped.casefold().startswith("**status:**"):
            status = stripped.split(":**", 1)[1].strip().casefold()
            break
        if stripped.casefold().startswith("status:"):
            status = stripped.split(":", 1)[1].strip().casefold()
            break
    status = status.replace("✅", "").replace("🚧", "").replace("📋", "").replace("⏸️", "").strip()
    if "supersed" in status:
        return "superseded"
    if "archive" in status:
        return "archived"
    if any(word in status for word in ("complete", "completed", "done")):
        return "completed"
    if "block" in status or "paused" in status:
        return "blocked"
    if "plan" in status or "draft" in status or "proposed" in status:
        return "planned"
    if "active" in status or "progress" in status or "execut" in status:
        return "active"
    return "unknown"


def build_impact_report(
    repo_root: Path,
    changed: tuple[str, ...],
    relationships: dict[str, Any],
    *,
    revision: str,
    dispositions: tuple[ReconciliationDisposition, ...] = (),
) -> ImpactReport:
    """Derive and resolve maintenance obligations for an exact changed-file set."""

    inventory = inventory_repository(repo_root)
    artifacts_by_path = {artifact.path: artifact for artifact in inventory.artifacts}
    tracked = set(artifacts_by_path)
    changed_set = set(changed)
    disposition_map = {item.obligation_id: item for item in dispositions}
    if len(disposition_map) != len(dispositions):
        raise ImpactObligationError("duplicate obligation_id in dispositions")
    obligations: list[ImpactObligation] = []
    diagnostics: list[str] = []
    seen_ids: set[str] = set()

    for spec in relationship_specs(relationships):
        if spec.maintenance == "lineage_only":
            continue
        matched_changes = sorted(
            path for path in changed if any(selector_path_matches(selector, path) for selector in spec.sources)
        )
        if not matched_changes:
            continue
        related_nodes = expand_selectors(spec.targets, inventory)
        if not related_nodes:
            diagnostics.append(f"{spec.provenance}: no tracked target resolves from {', '.join(spec.targets)}")
            continue
        for changed_path in matched_changes:
            for related_path, related_symbol in related_nodes:
                obligation_id = _obligation_id(changed_path, related_path, related_symbol, spec)
                if obligation_id in seen_ids:
                    continue
                seen_ids.add(obligation_id)
                related_available = artifacts_by_path[related_path].working_tree_state == "present"
                lifecycle: PlanLifecycle | None = None
                if spec.relation == "planned_by" and related_available:
                    lifecycle = plan_lifecycle(repo_root / related_path)
                historical_plan = lifecycle in {"completed", "superseded", "archived"}
                malformed_plan = lifecycle == "unknown"
                if related_path in changed_set and related_available and not historical_plan and not malformed_plan:
                    status: ObligationStatus = "updated"
                    disposition_reason: str | None = "Linked artifact changed in the same comparison."
                    successor = None
                else:
                    status, disposition_reason, successor = _apply_disposition(
                        obligation_id,
                        revision=revision,
                        disposition=disposition_map.get(obligation_id),
                        tracked_paths=tracked,
                    )
                    if not related_available and status == "unresolved":
                        disposition_reason = "Linked artifact is missing or a non-readable symlink in the working tree."
                    elif historical_plan and status == "unresolved":
                        disposition_reason = (
                            f"Linked plan is {lifecycle}; preserve history and reconcile through an exact-review "
                            "disposition or tracked successor/current-state authority."
                        )
                    elif malformed_plan and status == "unresolved":
                        disposition_reason = "Linked plan has no recognized lifecycle status and cannot satisfy freshness."
                    if historical_plan and status == "superseded" and successor is not None:
                        successor_artifact = artifacts_by_path[successor]
                        if successor_artifact.classification != "documentation":
                            raise ImpactObligationError(
                                f"completed-plan obligation {obligation_id} successor must be documentation authority: "
                                f"{successor}"
                            )
                obligations.append(
                    ImpactObligation(
                        obligation_id=obligation_id,
                        changed_path=changed_path,
                        related_path=related_path,
                        related_symbol=related_symbol,
                        relation=spec.relation,
                        reason=spec.reason,
                        maintenance=spec.maintenance,
                        provenance=spec.provenance,
                        related_lifecycle=lifecycle,
                        status=status,
                        disposition_reason=disposition_reason,
                        successor=successor,
                    )
                )

    unknown_dispositions = sorted(set(disposition_map) - seen_ids)
    if unknown_dispositions:
        raise ImpactObligationError(
            "dispositions reference obligations not present in this change set: " + ", ".join(unknown_dispositions)
        )
    obligations.sort(key=lambda item: (item.changed_path, item.related_path, item.related_symbol or "", item.relation))
    unresolved = sum(item.status in {"unresolved", "blocked"} for item in obligations) + len(diagnostics)
    return ImpactReport(
        schema_version=1,
        revision=revision,
        changed_paths=tuple(sorted(changed)),
        obligation_count=len(obligations),
        unresolved_count=unresolved,
        obligations=tuple(obligations),
        diagnostics=tuple(sorted(diagnostics)),
    )


def _load_relationships(repo_root: Path, config_path: str | Path) -> dict[str, Any]:
    """Load a relationship mapping for the impact-report CLI."""

    path = Path(config_path)
    if not path.is_absolute():
        path = repo_root / path
    if not path.exists():
        raise ImpactObligationError(f"relationship config does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ImpactObligationError("relationship config root must be a mapping")
    return loaded


def main(argv: list[str] | None = None) -> int:
    """Run report-only or strict reconciliation checks for a Git comparison."""

    parser = argparse.ArgumentParser(description="Derive relationship reconciliation obligations from changed files")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", default="scripts/relationships.yaml")
    parser.add_argument("--base", default="HEAD", help="Git diff base or revision range endpoint")
    parser.add_argument("--staged", action="store_true", help="Compare the staged index")
    parser.add_argument("--dispositions", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero for unresolved/blocked obligations")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        revision = review_revision(args.repo_root, base=args.base, staged=args.staged)
        report = build_impact_report(
            args.repo_root,
            changed_paths(args.repo_root, base=args.base, staged=args.staged),
            _load_relationships(args.repo_root, args.config),
            revision=revision,
            dispositions=load_dispositions(args.dispositions),
        )
    except (ContextPacketError, ImpactObligationError, OSError) as exc:
        parser.exit(2, f"impact-obligations: {exc}\n")
    print(report.to_json(pretty=args.pretty), end="")
    return 1 if args.strict and report.unresolved_count else 0


__all__ = [
    "ImpactObligation",
    "ImpactObligationError",
    "ImpactReport",
    "ReconciliationDisposition",
    "build_impact_report",
    "changed_paths",
    "current_revision",
    "load_dispositions",
    "main",
    "plan_lifecycle",
    "review_revision",
]
