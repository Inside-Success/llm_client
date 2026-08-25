"""Tests for deterministic codebase-wiki freshness enforcement."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.meta.check_codebase_wiki_freshness import (
    AuthoritySourceV1,
    CapsuleReferenceV1,
    CodeSurfaceV1,
    PathSetV1,
    WikiSourceManifestV1,
    compute_code_surface,
    evaluate_manifest,
)


def _git(repository: Path, *arguments: str) -> str:
    """Run Git in a fixture repository and return stripped stdout."""
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    """Create a committed repository with a representative wiki source surface."""
    repository = tmp_path / "repository"
    (repository / "llm_client").mkdir(parents=True)
    (repository / "llm_client" / "client.py").write_text(
        '"""Client facade."""\n\ndef call() -> str:\n    """Return a value."""\n    return "ok"\n',
        encoding="utf-8",
    )
    (repository / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (repository / "CLAUDE.md").write_text("# Authority\n", encoding="utf-8")
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.email", "fixture@example.com")
    _git(repository, "config", "user.name", "Fixture")
    _git(repository, "remote", "add", "origin", "https://github.com/BrianMills2718/llm_client.git")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "fixture")
    return repository


def _manifest(repository: Path, manifest_path: Path) -> WikiSourceManifestV1:
    """Build a valid manifest from a fixture's exact source."""
    revision = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    surface = CodeSurfaceV1(
        algorithm="sha256_path_nul_size_be64_blob_v1",
        path_sets=[PathSetV1(root="llm_client", suffixes=[".py"])],
        exact_paths=["pyproject.toml"],
        file_count=1,
        digest="0" * 64,
    )
    paths, digest = compute_code_surface(repository, surface, revision=revision)
    surface.file_count = len(paths)
    surface.digest = digest
    manifest = WikiSourceManifestV1(
        schema_version="1.1",
        document_type="codebase_wiki_source_manifest",
        project_id="llm_client",
        source_repository="BrianMills2718/llm_client",
        source_revision=revision,
        source_tree_revision=tree,
        code_surface=surface,
        authority_sources=[
            AuthoritySourceV1(
                path="CLAUDE.md",
                sha256=hashlib.sha256((repository / "CLAUDE.md").read_bytes()).hexdigest(),
            )
        ],
        capsules=[],
        network_sources=[],
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def test_matching_worktree_and_pinned_revision_pass(tmp_path: Path) -> None:
    """Accept unchanged source and current authority bytes."""
    repository = _repository(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(repository, manifest_path)

    receipt = evaluate_manifest(repository, manifest_path, manifest)

    assert receipt.ok is True
    assert receipt.errors == []
    assert {check.status for check in receipt.checks} == {"passed"}


def test_changed_or_new_tracked_source_fails(tmp_path: Path) -> None:
    """Reject both blob drift and path-set expansion below a selected root."""
    repository = _repository(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(repository, manifest_path)
    (repository / "llm_client" / "client.py").write_text("changed\n", encoding="utf-8")
    (repository / "llm_client" / "new.py").write_text("new = True\n", encoding="utf-8")
    _git(repository, "add", "llm_client/new.py")

    receipt = evaluate_manifest(repository, manifest_path, manifest)

    assert receipt.ok is False
    assert any(error.startswith("current_code_surface:") for error in receipt.errors)


def test_authority_drift_fails_without_code_change(tmp_path: Path) -> None:
    """Reject stale governing documentation independently of code bytes."""
    repository = _repository(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(repository, manifest_path)
    (repository / "CLAUDE.md").write_text("# Changed authority\n", encoding="utf-8")

    receipt = evaluate_manifest(repository, manifest_path, manifest)

    assert receipt.ok is False
    assert any(error.startswith("authority:CLAUDE.md:") for error in receipt.errors)


def test_external_capsule_reopens_exact_git_blob(tmp_path: Path) -> None:
    """Authenticate a maintained capsule without trusting a mutable checkout file."""
    repository = _repository(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(repository, manifest_path)
    external = tmp_path / "project-meta"
    artifact = external / "generated" / "capsule.json"
    artifact.parent.mkdir(parents=True)
    artifact_payload = {
        "capsule_id": "sha256:" + "1" * 64,
        "source": {
            "project_id": "inside-success-llm-client",
            "owner_class": "organization",
            "revision": "0" * 40,
            "tree_revision": "2" * 40,
        },
        "generator": {"project_meta_revision": "3" * 40},
    }
    artifact.write_text(json.dumps(artifact_payload) + "\n", encoding="utf-8")
    _git(external, "init", "-b", "main")
    _git(external, "config", "user.email", "fixture@example.com")
    _git(external, "config", "user.name", "Fixture")
    _git(external, "add", ".")
    _git(external, "commit", "-m", "capsule")
    revision = _git(external, "rev-parse", "HEAD")
    manifest.capsules = [
        CapsuleReferenceV1(
            project_id="inside-success-llm-client",
            owner_class="organization",
            status="accepted",
            source_revision="0" * 40,
            source_tree_revision="2" * 40,
            capsule_id="sha256:" + "1" * 64,
            file_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            generator_revision="3" * 40,
            artifact_revision=revision,
            repository_key="project-meta",
            path="generated/capsule.json",
        )
    ]

    passing = evaluate_manifest(
        repository,
        manifest_path,
        manifest,
        external_repositories={"project-meta": external},
        require_external=True,
    )
    manifest.capsules[0].file_sha256 = "0" * 64
    failing = evaluate_manifest(
        repository,
        manifest_path,
        manifest,
        external_repositories={"project-meta": external},
        require_external=True,
    )

    assert passing.ok is True
    assert failing.ok is False
    assert any(
        error.startswith("capsule_blob:inside-success-llm-client:")
        for error in failing.errors
    )
