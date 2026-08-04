"""Audit requirement-linked test semantics without treating test count as quality.

The auditor statically inventories authored Python test functions, reads
reviewed ``tests`` edges from ``scripts/relationships.yaml``, and emits
deterministic report-only findings. It never imports target code, executes
tests, infers behavioral authority from names, or recommends deletion.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import fnmatch
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

import yaml  # type: ignore[import-untyped, unused-ignore]

from enforced_planning.relationship_context import InventoryReport
from enforced_planning.relationship_context import inventory_repository


TestLevel: TypeAlias = Literal["unit", "integration", "contract", "end_to_end", "observed_trial"]
TestPolarity: TypeAlias = Literal[
    "positive", "negative_control", "regression", "failure_injection"
]
ExecutionRealism: TypeAlias = Literal[
    "mock", "fixture", "isolated_runtime", "deployed_runtime"
]
RiskLevel: TypeAlias = Literal["low", "medium", "high", "critical"]

ALLOWED_LEVELS = {"unit", "integration", "contract", "end_to_end", "observed_trial"}
ALLOWED_POLARITIES = {"positive", "negative_control", "regression", "failure_injection"}
ALLOWED_REALISM = {"mock", "fixture", "isolated_runtime", "deployed_runtime"}
ALLOWED_RISKS = {"low", "medium", "high", "critical"}
NEGATIVE_POLARITIES = {"negative_control", "failure_injection"}
SYNTHETIC_REALISM = {"mock", "fixture"}


class TestRelationshipError(RuntimeError):
    """Report malformed test-audit configuration or relationship semantics."""


@dataclass(frozen=True)
class TestCaseRecord:
    """Represent one authored Python test function or class method."""

    test_id: str
    path: str
    qualified_name: str
    line: int


@dataclass(frozen=True)
class RequirementRecord:
    """Represent one declared behavioral authority whose proof can be audited."""

    requirement_id: str
    source: str
    risk_level: RiskLevel


@dataclass(frozen=True)
class TestEdge:
    """Normalize one reviewed test-to-boundary relationship."""

    edge_id: str
    test_selectors: tuple[str, ...]
    implementation_boundaries: tuple[str, ...]
    requirement_refs: tuple[str, ...]
    level: TestLevel | None
    polarity: TestPolarity | None
    execution_realism: ExecutionRealism | None
    failure_modes: tuple[str, ...]
    risk_level: RiskLevel | None
    reason: str


@dataclass(frozen=True)
class TestAuditFinding:
    """Describe one report-only test-purpose, coverage, or evidence concern."""

    code: str
    severity: str
    subject: str
    message: str
    related: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestAuditReport:
    """Provide deterministic test inventory, linkage metrics, and findings."""

    schema_version: int
    mode: str
    scoped_test_count: int
    linked_test_count: int
    semantically_linked_test_count: int
    declared_requirement_count: int
    requirements_with_evidence_count: int
    reviewed_edge_count: int
    tests: tuple[TestCaseRecord, ...]
    requirements: tuple[RequirementRecord, ...]
    edges: tuple[TestEdge, ...]
    findings: tuple[TestAuditFinding, ...]

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible fields."""

        return asdict(self)

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize without timestamps or workspace-specific paths."""

        return json.dumps(
            self.to_dict(),
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ) + "\n"

    def to_markdown(self) -> str:
        """Render a compact human review surface from the same report data."""

        lines = [
            "# Test Relationship Audit",
            "",
            "> Report-only. Findings are review candidates, not deletion or hard-gate authority.",
            "",
            "## Summary",
            "",
            f"- Authored tests in scope: **{self.scoped_test_count}**",
            f"- Tests linked by reviewed edges: **{self.linked_test_count}**",
            f"- Tests linked by semantically complete edges: **{self.semantically_linked_test_count}**",
            f"- Reviewed test edges: **{self.reviewed_edge_count}**",
            "- Declared requirements with reviewed test evidence: "
            f"**{self.requirements_with_evidence_count}/{self.declared_requirement_count}**",
            f"- Findings: **{len(self.findings)}**",
            "",
            "## Findings",
            "",
        ]
        if not self.findings:
            lines.append("No findings in the selected scope.")
        else:
            lines.extend(["| Severity | Code | Subject | Finding |", "|---|---|---|---|"])
            for finding in self.findings:
                message = finding.message.replace("|", "\\|").replace("\n", " ")
                subject = finding.subject.replace("|", "\\|")
                lines.append(f"| {finding.severity} | `{finding.code}` | `{subject}` | {message} |")
        return "\n".join(lines) + "\n"


def _strings(value: Any, *, field: str) -> tuple[str, ...]:
    """Normalize a scalar/list string field while rejecting ambiguous shapes."""

    if value is None:
        return ()
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return (text,) if text else ()
    if isinstance(value, list) and all(isinstance(item, (str, int)) for item in value):
        return tuple(text for item in value if (text := str(item).strip()))
    raise TestRelationshipError(f"{field} must be a string, integer, or list")


def _enum(value: Any, *, field: str, allowed: set[str]) -> str | None:
    """Normalize an optional enum and fail loudly on misspellings."""

    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip()
    if normalized not in allowed:
        raise TestRelationshipError(
            f"{field} has unsupported value {normalized!r}; expected one of {sorted(allowed)}"
        )
    return normalized


def _selectors(edge: dict[str, Any], primary: str, plural: str, alias: str) -> tuple[str, ...]:
    """Read one selector side using the V2 and compatibility field names."""

    return _strings(edge.get(plural, edge.get(primary, edge.get(alias))), field=plural)


def _looks_like_test(selector: str) -> bool:
    """Identify the test side of an edge from its repository-relative selector."""

    path = selector.partition("::")[0]
    name = PurePosixPath(path).name
    return path.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")


def parse_requirements(data: dict[str, Any]) -> tuple[RequirementRecord, ...]:
    """Parse optional behavioral authorities without duplicating requirement prose."""

    raw = data.get("requirements", []) or []
    if not isinstance(raw, list):
        raise TestRelationshipError("requirements must be a list")
    records: list[RequirementRecord] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TestRelationshipError(f"requirements[{index}] must be a mapping")
        requirement_id = str(item.get("id", "")).strip()
        source = str(item.get("source", "")).strip()
        risk = _enum(item.get("risk_level", "medium"), field=f"requirements[{index}].risk_level", allowed=ALLOWED_RISKS)
        if not requirement_id or not source or risk is None:
            raise TestRelationshipError(f"requirements[{index}] requires id, source, and risk_level")
        if requirement_id in seen:
            raise TestRelationshipError(f"duplicate requirement id {requirement_id!r}")
        if "description" in item or "summary" in item:
            raise TestRelationshipError(
                f"requirements[{index}] duplicates authority prose; use source-local text"
            )
        seen.add(requirement_id)
        records.append(RequirementRecord(requirement_id, source, risk))  # type: ignore[arg-type]
    return tuple(sorted(records, key=lambda record: record.requirement_id))


def parse_test_edges(data: dict[str, Any]) -> tuple[TestEdge, ...]:
    """Parse reviewed ``tests`` edges while preserving legacy incomplete edges."""

    raw = data.get("relationships", data.get("edges", [])) or []
    if not isinstance(raw, list):
        raise TestRelationshipError("relationships/edges must be a list")
    edges: list[TestEdge] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TestRelationshipError(f"relationships[{index}] must be a mapping")
        if str(item.get("relation", "")).strip() != "tests":
            continue
        left = _selectors(item, "source", "sources", "from")
        right = _selectors(item, "target", "targets", "to")
        if not left or not right:
            raise TestRelationshipError(f"relationships[{index}] tests edge needs both sides")
        test_selectors = tuple(selector for selector in (*left, *right) if _looks_like_test(selector))
        boundaries = tuple(selector for selector in (*left, *right) if not _looks_like_test(selector))
        if not test_selectors or not boundaries:
            raise TestRelationshipError(
                f"relationships[{index}] tests edge must connect a test selector to a non-test boundary"
            )
        reason = str(item.get("reason", "")).strip()
        if not reason:
            raise TestRelationshipError(f"relationships[{index}] must explain the test edge")
        edges.append(
            TestEdge(
                edge_id=f"relationships[{index}]",
                test_selectors=tuple(sorted(set(test_selectors))),
                implementation_boundaries=tuple(sorted(set(boundaries))),
                requirement_refs=_strings(
                    item.get("requirement_refs", item.get("acceptance_refs")),
                    field=f"relationships[{index}].requirement_refs",
                ),
                level=_enum(item.get("level"), field=f"relationships[{index}].level", allowed=ALLOWED_LEVELS),  # type: ignore[arg-type]
                polarity=_enum(item.get("polarity"), field=f"relationships[{index}].polarity", allowed=ALLOWED_POLARITIES),  # type: ignore[arg-type]
                execution_realism=_enum(
                    item.get("execution_realism"),
                    field=f"relationships[{index}].execution_realism",
                    allowed=ALLOWED_REALISM,
                ),  # type: ignore[arg-type]
                failure_modes=_strings(
                    item.get("failure_modes"), field=f"relationships[{index}].failure_modes"
                ),
                risk_level=_enum(
                    item.get("risk_level"),
                    field=f"relationships[{index}].risk_level",
                    allowed=ALLOWED_RISKS,
                ),  # type: ignore[arg-type]
                reason=reason,
            )
        )
    return tuple(edges)


def inventory_tests(inventory: InventoryReport, includes: tuple[str, ...]) -> tuple[TestCaseRecord, ...]:
    """Return every authored test function/method in the selected path scope."""

    records: list[TestCaseRecord] = []
    for artifact in inventory.artifacts:
        if artifact.classification != "test" or artifact.format != "python":
            continue
        if includes and not any(fnmatch.fnmatch(artifact.path, pattern) for pattern in includes):
            continue
        for symbol in artifact.symbols:
            if symbol.kind not in {"function", "method"}:
                continue
            if not symbol.qualified_name.rsplit(".", 1)[-1].startswith("test_"):
                continue
            records.append(
                TestCaseRecord(symbol.symbol_id, artifact.path, symbol.qualified_name, symbol.line)
            )
    return tuple(sorted(records, key=lambda record: record.test_id))


def _selector_matches(selector: str, test: TestCaseRecord) -> bool:
    """Match file/glob or exact ``file::symbol`` selectors to an authored test."""

    path, separator, symbol = selector.partition("::")
    if not fnmatch.fnmatch(test.path, path):
        return False
    return not separator or symbol == test.qualified_name


def _selector_in_scope(selector: str, includes: tuple[str, ...]) -> bool:
    """Return whether a reviewed test selector belongs to the requested audit scope."""

    path = selector.partition("::")[0]
    return not includes or any(fnmatch.fnmatch(path, pattern) for pattern in includes)


def _finding(
    code: str, severity: str, subject: str, message: str, related: tuple[str, ...] = ()
) -> TestAuditFinding:
    """Construct one stable finding with sorted related identifiers."""

    return TestAuditFinding(code, severity, subject, message, tuple(sorted(set(related))))


def _edge_is_complete(edge: TestEdge) -> bool:
    """Return whether an edge carries every policy-required test semantic."""

    return bool(
        edge.requirement_refs
        and edge.level
        and edge.polarity
        and edge.execution_realism
        and edge.failure_modes
        and edge.risk_level
    )


def _requirement_source_exists(repo_root: Path, requirement: RequirementRecord) -> bool:
    """Return whether a requirement's source authority resolves to a local file."""

    source_path = requirement.source.partition("#")[0]
    if not source_path or Path(source_path).is_absolute():
        return False
    return (repo_root / source_path).is_file()


def audit_test_relationships(
    repo_root: Path,
    relationships: dict[str, Any],
    *,
    includes: tuple[str, ...] = ("tests/**/*.py", "tests/*.py"),
) -> TestAuditReport:
    """Compile a deterministic report-only audit for one governed repository."""

    inventory = inventory_repository(repo_root)
    tests = inventory_tests(inventory, includes)
    requirements = parse_requirements(relationships)
    declared_requirement_ids = {
        requirement.requirement_id for requirement in requirements
    }
    valid_requirement_ids = {
        requirement.requirement_id
        for requirement in requirements
        if _requirement_source_exists(repo_root, requirement)
    }
    edges = tuple(
        edge
        for edge in parse_test_edges(relationships)
        if any(_selector_in_scope(selector, includes) for selector in edge.test_selectors)
    )
    matched_by_edge: dict[str, tuple[str, ...]] = {
        edge.edge_id: tuple(
            test.test_id
            for test in tests
            if any(_selector_matches(selector, test) for selector in edge.test_selectors)
        )
        for edge in edges
    }
    linked_ids = {test_id for matches in matched_by_edge.values() for test_id in matches}
    evidence_eligible_edges = {
        edge.edge_id
        for edge in edges
        if _edge_is_complete(edge)
        and matched_by_edge[edge.edge_id]
        and set(edge.requirement_refs) <= valid_requirement_ids
    }
    semantically_linked_ids = {
        test_id
        for edge in edges
        if edge.edge_id in evidence_eligible_edges
        for test_id in matched_by_edge[edge.edge_id]
    }
    findings: list[TestAuditFinding] = []

    for test in tests:
        if test.test_id not in linked_ids:
            findings.append(
                _finding(
                    "TEST_UNLINKED",
                    "info",
                    test.test_id,
                    "Authored test has no reviewed behavioral relationship in the selected scope.",
                )
            )

    for edge in edges:
        unknown_refs = sorted(set(edge.requirement_refs) - declared_requirement_ids)
        for requirement_ref in unknown_refs:
            findings.append(
                _finding(
                    "UNKNOWN_REQUIREMENT_REF",
                    "high",
                    edge.edge_id,
                    f"Test edge references undeclared requirement {requirement_ref!r}.",
                    (requirement_ref,),
                )
            )
        if not matched_by_edge[edge.edge_id]:
            findings.append(
                _finding(
                    "TEST_SELECTOR_EMPTY",
                    "moderate",
                    edge.edge_id,
                    "Reviewed test selector matches no authored test in the selected scope.",
                    edge.test_selectors,
                )
            )
        missing = [
            name
            for name, value in (
                ("requirement_refs", edge.requirement_refs),
                ("level", edge.level),
                ("polarity", edge.polarity),
                ("execution_realism", edge.execution_realism),
                ("failure_modes", edge.failure_modes),
                ("risk_level", edge.risk_level),
            )
            if not value
        ]
        if missing:
            findings.append(
                _finding(
                    "TEST_EDGE_INCOMPLETE",
                    "moderate",
                    edge.edge_id,
                    f"Reviewed test edge lacks semantic fields: {', '.join(missing)}.",
                    (*edge.test_selectors, *edge.implementation_boundaries),
                )
            )

    for requirement in requirements:
        if requirement.requirement_id not in valid_requirement_ids:
            findings.append(
                _finding(
                    "REQUIREMENT_SOURCE_MISSING",
                    "high",
                    requirement.requirement_id,
                    "Declared requirement source does not resolve to a local file.",
                    (requirement.source,),
                )
            )

    edges_by_requirement: dict[str, list[TestEdge]] = {}
    for edge in edges:
        if edge.edge_id not in evidence_eligible_edges:
            continue
        for requirement_ref in edge.requirement_refs:
            edges_by_requirement.setdefault(requirement_ref, []).append(edge)
    for requirement in requirements:
        proof = edges_by_requirement.get(requirement.requirement_id, [])
        if not proof:
            findings.append(
                _finding(
                    "REQUIREMENT_WITHOUT_TEST_EVIDENCE",
                    "high" if requirement.risk_level in {"high", "critical"} else "moderate",
                    requirement.requirement_id,
                    "Declared requirement has no reviewed test relationship.",
                    (requirement.source,),
                )
            )
            continue
        if all(edge.execution_realism in SYNTHETIC_REALISM for edge in proof):
            findings.append(
                _finding(
                    "AUTHORITY_SYNTHETIC_ONLY",
                    "moderate",
                    requirement.requirement_id,
                    "All reviewed proof is mock- or fixture-based; no runtime proof is linked.",
                    tuple(edge.edge_id for edge in proof),
                )
            )
        if all(edge.level == "unit" for edge in proof):
            findings.append(
                _finding(
                    "AUTHORITY_UNIT_ONLY",
                    "moderate",
                    requirement.requirement_id,
                    "All reviewed proof is unit-level; no contract, integration, end-to-end, or observed trial is linked.",
                    tuple(edge.edge_id for edge in proof),
                )
            )
        if requirement.risk_level in {"high", "critical"} and not any(
            edge.polarity in NEGATIVE_POLARITIES for edge in proof
        ):
            findings.append(
                _finding(
                    "HIGH_RISK_NO_NEGATIVE_CONTROL",
                    "high",
                    requirement.requirement_id,
                    "High-risk requirement has no reviewed negative-control or failure-injection proof.",
                    tuple(edge.edge_id for edge in proof),
                )
            )

    semantic_groups: dict[tuple[object, ...], list[TestEdge]] = {}
    for edge in edges:
        if not edge.requirement_refs:
            continue
        signature = (
            edge.requirement_refs,
            edge.implementation_boundaries,
            edge.level,
            edge.polarity,
            edge.execution_realism,
            edge.failure_modes,
        )
        semantic_groups.setdefault(signature, []).append(edge)
    for group in semantic_groups.values():
        if len(group) >= 3:
            findings.append(
                _finding(
                    "POSSIBLE_DUPLICATE_EDGE_CLUSTER",
                    "info",
                    ",".join(group[0].requirement_refs),
                    f"{len(group)} reviewed edges declare the same semantic proof shape; review for consolidation, but do not delete automatically.",
                    tuple(edge.edge_id for edge in group),
                )
            )

    findings.sort(key=lambda finding: (finding.code, finding.subject, finding.message))
    requirements_with_evidence = {
        requirement.requirement_id
        for requirement in requirements
        if edges_by_requirement.get(requirement.requirement_id)
    }
    return TestAuditReport(
        schema_version=1,
        mode="report_only",
        scoped_test_count=len(tests),
        linked_test_count=len(linked_ids),
        semantically_linked_test_count=len(semantically_linked_ids),
        declared_requirement_count=len(requirements),
        requirements_with_evidence_count=len(requirements_with_evidence),
        reviewed_edge_count=len(edges),
        tests=tests,
        requirements=requirements,
        edges=edges,
        findings=tuple(findings),
    )


def load_relationships(path: Path) -> dict[str, Any]:
    """Load one relationships mapping and reject missing or invalid roots."""

    if not path.exists():
        raise TestRelationshipError(f"relationships file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TestRelationshipError("relationships YAML must be a mapping")
    return data


def audit_includes(data: dict[str, Any]) -> tuple[str, ...]:
    """Read the optional report-only audit scope from relationships config."""

    raw = data.get("test_audit", {}) or {}
    if not isinstance(raw, dict):
        raise TestRelationshipError("test_audit must be a mapping")
    mode = str(raw.get("mode", "report_only")).strip()
    if mode != "report_only":
        raise TestRelationshipError(
            "test_audit.mode must remain report_only until calibrated enforcement is separately approved"
        )
    includes = _strings(raw.get("include"), field="test_audit.include")
    return includes or ("tests/**/*.py", "tests/*.py")


def main(argv: list[str] | None = None) -> int:
    """Run the report-only test relationship audit CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--relationships", default="scripts/relationships.yaml")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    relationships_path = Path(args.relationships)
    if not relationships_path.is_absolute():
        relationships_path = root / relationships_path
    try:
        relationships = load_relationships(relationships_path)
        includes = tuple(args.include) or audit_includes(relationships)
        report = audit_test_relationships(
            root, relationships, includes=includes
        )
    except TestRelationshipError as exc:
        parser.error(str(exc))
    rendered = report.to_json(pretty=True) if args.format == "json" else report.to_markdown()
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


__all__ = [
    "TestAuditReport",
    "TestRelationshipError",
    "audit_test_relationships",
    "audit_includes",
    "inventory_tests",
    "load_relationships",
    "main",
    "parse_requirements",
    "parse_test_edges",
]
