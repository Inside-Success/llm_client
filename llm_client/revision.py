"""Truthful installed revision identity for cross-project evidence."""

from __future__ import annotations

import os
import re
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git_output(package_directory: Path, *arguments: str) -> str | None:
    """Return bounded Git output for the package checkout, if available."""

    try:
        result = subprocess.run(
            ["git", "-C", str(package_directory), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _source_checkout_revision(package_directory: Path) -> str | None:
    """Return HEAD only when this import is the checkout's top-level package."""

    root_text = _git_output(package_directory, "rev-parse", "--show-toplevel")
    if not root_text:
        return None
    root = Path(root_text).resolve()
    if (root / "llm_client").resolve() != package_directory.resolve():
        return None
    if not (root / "pyproject.toml").is_file():
        return None
    revision = _git_output(package_directory, "rev-parse", "HEAD")
    if revision is None or _COMMIT_SHA.fullmatch(revision) is None:
        return None
    return revision


def installed_llm_client_revision() -> str:
    """Return the exact source HEAD or installed distribution-version identity."""

    source_revision = _source_checkout_revision(Path(__file__).resolve().parent)
    if source_revision is not None:
        return source_revision
    try:
        return f"package:{version('llm-client')}"
    except PackageNotFoundError:
        return "package:uninstalled-source"


def validated_llm_client_revision(configured: str | None = None) -> str:
    """Return installed identity and reject a conflicting configured claim."""

    installed = installed_llm_client_revision()
    claimed = (
        os.getenv("LLM_CLIENT_REVISION", "")
        if configured is None
        else configured
    ).strip()
    if claimed and claimed != installed:
        raise ValueError(
            "configured LLM_CLIENT_REVISION "
            f"{claimed!r} does not match installed llm_client revision {installed!r}"
        )
    return installed


__all__ = [
    "installed_llm_client_revision",
    "validated_llm_client_revision",
]
