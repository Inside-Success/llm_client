#!/usr/bin/env python3
"""Check the codebase wiki against its exact code, authority, and capsule inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class FreshnessError(ValueError):
    """Raised when a freshness input cannot be observed exactly."""


class StrictModel(BaseModel):
    """Reject fields that are not part of the durable manifest contract."""

    model_config = ConfigDict(extra="forbid")


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("path must be a safe repository-relative POSIX path")
    return value


class PathSetV1(StrictModel):
    """Select tracked source files below one repository-relative root."""

    root: str
    suffixes: list[str] = Field(min_length=1)

    _validate_root = field_validator("root")(_relative_path)

    @field_validator("suffixes")
    @classmethod
    def validate_suffixes(cls, values: list[str]) -> list[str]:
        """Require canonical, unique filename suffixes."""
        if values != sorted(set(values)) or any(not value.startswith(".") for value in values):
            raise ValueError("suffixes must be sorted unique values beginning with '.'")
        return values


class CodeSurfaceV1(StrictModel):
    """Bind one deterministic subset of tracked source to a content digest."""

    algorithm: Literal["sha256_path_nul_size_be64_blob_v1"]
    path_sets: list[PathSetV1] = Field(min_length=1)
    exact_paths: list[str]
    file_count: int = Field(ge=1)
    digest: str

    @field_validator("exact_paths")
    @classmethod
    def validate_exact_paths(cls, values: list[str]) -> list[str]:
        """Require canonical, unique exact paths."""
        validated = [_relative_path(value) for value in values]
        if validated != sorted(set(validated)):
            raise ValueError("exact_paths must be sorted and unique")
        return validated

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        """Require a lowercase SHA-256 digest."""
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("digest must be 64 lowercase hexadecimal characters")
        return value


class AuthoritySourceV1(StrictModel):
    """Pin one current canonical document consumed by the wiki."""

    path: str
    sha256: str

    _validate_path = field_validator("path")(_relative_path)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Require a lowercase SHA-256 digest."""
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class CapsuleReferenceV1(StrictModel):
    """Identify one personal or company capsule without merging ownership."""

    project_id: str
    owner_class: Literal["personal", "organization"]
    status: Literal["accepted", "verified_not_published"]
    source_revision: str
    source_tree_revision: str
    capsule_id: str
    file_sha256: str
    generator_revision: str
    artifact_revision: str | None
    repository_key: str | None
    path: str | None

    _validate_path = field_validator("path")(
        lambda value: None if value is None else _relative_path(value)
    )

    @field_validator(
        "source_revision",
        "source_tree_revision",
        "generator_revision",
        "artifact_revision",
    )
    @classmethod
    def validate_revision(cls, value: str | None) -> str | None:
        """Require an exact Git object revision."""
        if value is None:
            return None
        if REVISION_RE.fullmatch(value) is None:
            raise ValueError("revision must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("capsule_id")
    @classmethod
    def validate_capsule_id(cls, value: str) -> str:
        """Require the capsule's content-addressed identifier."""
        if not value.startswith("sha256:") or SHA256_RE.fullmatch(value[7:]) is None:
            raise ValueError("capsule_id must be sha256:<64 lowercase hex>")
        return value

    @field_validator("file_sha256")
    @classmethod
    def validate_file_sha256(cls, value: str) -> str:
        """Require a lowercase file SHA-256 digest."""
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("file_sha256 must be 64 lowercase hexadecimal characters")
        return value


class NetworkSourceV1(StrictModel):
    """Pin one external default branch whose movement makes the wiki stale."""

    project_id: str
    remote_url: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)
    expected_revision: str

    @field_validator("expected_revision")
    @classmethod
    def validate_expected_revision(cls, value: str) -> str:
        """Require an exact Git revision."""
        if REVISION_RE.fullmatch(value) is None:
            raise ValueError("expected_revision must be 40 lowercase hexadecimal characters")
        return value


class WikiSourceManifestV1(StrictModel):
    """Describe every mutable input used by the compiled codebase wiki."""

    schema_version: Literal["1.1"]
    document_type: Literal["codebase_wiki_source_manifest"]
    project_id: Literal["llm_client"]
    source_repository: Literal["BrianMills2718/llm_client"]
    source_revision: str
    source_tree_revision: str
    code_surface: CodeSurfaceV1
    authority_sources: list[AuthoritySourceV1]
    capsules: list[CapsuleReferenceV1]
    network_sources: list[NetworkSourceV1]

    @field_validator("source_revision", "source_tree_revision")
    @classmethod
    def validate_source_revision(cls, value: str) -> str:
        """Require exact source and tree revisions."""
        if REVISION_RE.fullmatch(value) is None:
            raise ValueError("source revision must be 40 lowercase hexadecimal characters")
        return value


class FreshnessCheckV1(StrictModel):
    """Record one deterministic pass or failure."""

    check_id: str
    status: Literal["passed", "failed", "skipped"]
    detail: str


class FreshnessReceiptV1(StrictModel):
    """Report the complete codebase-wiki freshness result."""

    schema_version: Literal["1.0"] = "1.0"
    document_type: Literal["codebase_wiki_freshness_receipt"] = (
        "codebase_wiki_freshness_receipt"
    )
    ok: bool
    manifest: str
    checks: list[FreshnessCheckV1]
    errors: list[str]


GitRunner = Callable[[Path, list[str]], subprocess.CompletedProcess[bytes]]


def _run_git(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run one non-interactive Git read against a resolved repository."""
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        check=False,
    )


def _git_output(
    repository: Path,
    arguments: list[str],
    *,
    runner: GitRunner = _run_git,
) -> bytes:
    """Return exact Git stdout or raise a visible observation error."""
    result = runner(repository, arguments)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise FreshnessError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _selected_paths(
    repository: Path,
    surface: CodeSurfaceV1,
    *,
    revision: str | None,
    runner: GitRunner = _run_git,
) -> list[str]:
    """Return the canonical tracked path set selected by one surface contract."""
    pathspecs = [item.root for item in surface.path_sets] + surface.exact_paths
    arguments = (
        ["ls-files", "-z", "--", *pathspecs]
        if revision is None
        else ["ls-tree", "-r", "-z", "--name-only", revision, "--", *pathspecs]
    )
    available = {
        item.decode("utf-8")
        for item in _git_output(repository, arguments, runner=runner).split(b"\0")
        if item
    }
    selected = set(surface.exact_paths)
    for path_set in surface.path_sets:
        prefix = path_set.root.rstrip("/") + "/"
        selected.update(
            path
            for path in available
            if (path == path_set.root or path.startswith(prefix))
            and any(path.endswith(suffix) for suffix in path_set.suffixes)
        )
    missing = sorted(selected - available)
    if missing:
        raise FreshnessError(f"selected paths are not tracked: {', '.join(missing)}")
    return sorted(selected)


def _surface_digest(paths: list[str], read_blob: Callable[[str], bytes]) -> str:
    """Hash paths and bytes with unambiguous deterministic framing."""
    digest = hashlib.sha256()
    for path in paths:
        blob = read_blob(path)
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(blob).to_bytes(8, byteorder="big"))
        digest.update(blob)
    return digest.hexdigest()


def compute_code_surface(
    repository: Path,
    surface: CodeSurfaceV1,
    *,
    revision: str | None = None,
    runner: GitRunner = _run_git,
) -> tuple[list[str], str]:
    """Compute the selected working-tree or exact-revision source digest."""
    repository = repository.resolve(strict=True)
    paths = _selected_paths(repository, surface, revision=revision, runner=runner)
    if revision is None:
        return paths, _surface_digest(paths, lambda path: (repository / path).read_bytes())
    return paths, _surface_digest(
        paths,
        lambda path: _git_output(repository, ["show", f"{revision}:{path}"], runner=runner),
    )


def _normalize_remote(remote: str) -> str:
    """Normalize common HTTPS and SSH GitHub remotes to owner/repository."""
    value = remote.strip().removesuffix("/").removesuffix(".git")
    if value.startswith("git@") and ":" in value:
        return value.split(":", 1)[1]
    marker = "github.com/"
    if marker in value:
        return value.split(marker, 1)[1]
    return value


def _parse_external_repositories(values: list[str]) -> dict[str, Path]:
    """Parse repeated key=path external repository arguments."""
    repositories: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or not key or not raw_path:
            raise FreshnessError("external repositories must use key=/absolute/path")
        if key in repositories:
            raise FreshnessError(f"duplicate external repository key: {key}")
        repositories[key] = Path(raw_path).expanduser().resolve(strict=True)
    return repositories


def evaluate_manifest(
    repository: Path,
    manifest_path: Path,
    manifest: WikiSourceManifestV1,
    *,
    external_repositories: dict[str, Path] | None = None,
    require_external: bool = False,
    network: bool = False,
    runner: GitRunner = _run_git,
) -> FreshnessReceiptV1:
    """Evaluate all requested freshness boundaries and return a typed receipt."""
    repository = repository.resolve(strict=True)
    checks: list[FreshnessCheckV1] = []
    errors: list[str] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            FreshnessCheckV1(
                check_id=check_id,
                status="passed" if passed else "failed",
                detail=detail,
            )
        )
        if not passed:
            errors.append(f"{check_id}: {detail}")

    try:
        origin = _git_output(repository, ["remote", "get-url", "origin"], runner=runner)
        identity = _normalize_remote(origin.decode("utf-8"))
        record(
            "source_repository_identity",
            identity == manifest.source_repository,
            f"observed={identity} expected={manifest.source_repository}",
        )
        tree = _git_output(
            repository,
            ["rev-parse", f"{manifest.source_revision}^{{tree}}"],
            runner=runner,
        ).decode("utf-8").strip()
        record(
            "source_tree_revision",
            tree == manifest.source_tree_revision,
            f"observed={tree} expected={manifest.source_tree_revision}",
        )
        pinned_paths, pinned_digest = compute_code_surface(
            repository,
            manifest.code_surface,
            revision=manifest.source_revision,
            runner=runner,
        )
        current_paths, current_digest = compute_code_surface(
            repository,
            manifest.code_surface,
            runner=runner,
        )
        expected = manifest.code_surface
        record(
            "pinned_code_surface",
            len(pinned_paths) == expected.file_count and pinned_digest == expected.digest,
            f"files={len(pinned_paths)} digest={pinned_digest}",
        )
        record(
            "current_code_surface",
            current_paths == pinned_paths and current_digest == expected.digest,
            f"files={len(current_paths)} digest={current_digest}",
        )
    except (FreshnessError, OSError) as exc:
        record("code_surface_observation", False, str(exc))

    for authority in manifest.authority_sources:
        try:
            observed = hashlib.sha256((repository / authority.path).read_bytes()).hexdigest()
            record(
                f"authority:{authority.path}",
                observed == authority.sha256,
                f"observed={observed} expected={authority.sha256}",
            )
        except OSError as exc:
            record(f"authority:{authority.path}", False, str(exc))

    available_external = external_repositories or {}
    for capsule in manifest.capsules:
        if (
            capsule.repository_key is None
            or capsule.path is None
            or capsule.artifact_revision is None
        ):
            checks.append(
                FreshnessCheckV1(
                    check_id=(
                        f"capsule:{capsule.project_id}:"
                        f"{capsule.source_revision[:7]}"
                    ),
                    status="skipped",
                    detail="no maintained external artifact is declared",
                )
            )
            continue
        external = available_external.get(capsule.repository_key)
        if external is None:
            status: Literal["failed", "skipped"] = "failed" if require_external else "skipped"
            checks.append(
                FreshnessCheckV1(
                    check_id=(
                        f"capsule:{capsule.project_id}:"
                        f"{capsule.source_revision[:7]}"
                    ),
                    status=status,
                    detail=f"external repository {capsule.repository_key!r} was not supplied",
                )
            )
            if require_external:
                errors.append(
                    f"capsule:{capsule.project_id}:{capsule.source_revision[:7]}: "
                    "external repository "
                    f"{capsule.repository_key!r} was not supplied"
                )
            continue
        try:
            artifact = _git_output(
                external,
                ["show", f"{capsule.artifact_revision}:{capsule.path}"],
                runner=runner,
            )
            observed = hashlib.sha256(artifact).hexdigest()
            record(
                f"capsule_blob:{capsule.project_id}:{capsule.source_revision[:7]}",
                observed == capsule.file_sha256,
                f"observed={observed} expected={capsule.file_sha256}",
            )
            payload = json.loads(artifact)
            source = payload["source"]
            generator = payload["generator"]
            binding = {
                "capsule_id": payload["capsule_id"],
                "project_id": source["project_id"],
                "owner_class": source["owner_class"],
                "source_revision": source["revision"],
                "source_tree_revision": source["tree_revision"],
                "generator_revision": generator["project_meta_revision"],
            }
            expected_binding = {
                "capsule_id": capsule.capsule_id,
                "project_id": capsule.project_id,
                "owner_class": capsule.owner_class,
                "source_revision": capsule.source_revision,
                "source_tree_revision": capsule.source_tree_revision,
                "generator_revision": capsule.generator_revision,
            }
            record(
                f"capsule_binding:{capsule.project_id}:{capsule.source_revision[:7]}",
                binding == expected_binding,
                f"observed={binding} expected={expected_binding}",
            )
        except (FreshnessError, KeyError, TypeError, ValueError) as exc:
            record(
                f"capsule:{capsule.project_id}:{capsule.source_revision[:7]}",
                False,
                str(exc),
            )

    if network:
        for source in manifest.network_sources:
            try:
                result = subprocess.run(
                    [
                        "git",
                        "ls-remote",
                        "--exit-code",
                        source.remote_url,
                        f"refs/heads/{source.default_branch}",
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                revisions = [line.split()[0] for line in result.stdout.splitlines() if line]
                if result.returncode != 0 or len(revisions) != 1:
                    detail = result.stderr.strip() or "remote branch did not resolve exactly once"
                    raise FreshnessError(detail)
                record(
                    f"network:{source.project_id}",
                    revisions[0] == source.expected_revision,
                    f"observed={revisions[0]} expected={source.expected_revision}",
                )
            except (FreshnessError, OSError) as exc:
                record(f"network:{source.project_id}", False, str(exc))

    return FreshnessReceiptV1(
        ok=not errors,
        manifest=str(manifest_path),
        checks=checks,
        errors=errors,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the deterministic freshness-check interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("roadmap/codebase/raw/source-manifest-4f7ecfa-company-f4a08fe.json"),
    )
    parser.add_argument(
        "--external-repository",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="Verify capsule bytes from an exact revision in another repository",
    )
    parser.add_argument("--require-external", action="store_true")
    parser.add_argument("--network", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Validate one manifest and print its machine-readable freshness receipt."""
    args = parse_args(argv)
    try:
        manifest_path = args.manifest.resolve(strict=True)
        manifest = WikiSourceManifestV1.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        receipt = evaluate_manifest(
            args.repository,
            manifest_path,
            manifest,
            external_repositories=_parse_external_repositories(args.external_repository),
            require_external=args.require_external,
            network=args.network,
        )
    except (FreshnessError, OSError, ValidationError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if receipt.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
