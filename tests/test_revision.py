"""Installed shared-client revision identity and mismatch controls."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import llm_client.revision as revision_module
from llm_client.revision import (
    _source_checkout_revision,
    installed_llm_client_revision,
    validated_llm_client_revision,
)


def test_source_checkout_revision_requires_top_level_imported_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    package = checkout / "llm_client"
    package.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='llm-client'\n")
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout=f"{checkout}\n"),
            SimpleNamespace(returncode=0, stdout=f"{'a' * 40}\n"),
        )
    )
    monkeypatch.setattr(revision_module.subprocess, "run", lambda *args, **kwargs: next(responses))

    assert _source_checkout_revision(package) == "a" * 40


def test_source_checkout_revision_rejects_parent_application_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = tmp_path / "application"
    package = application / ".venv" / "site-packages" / "llm_client"
    package.mkdir(parents=True)
    (application / "pyproject.toml").write_text("[project]\nname='application'\n")
    monkeypatch.setattr(
        revision_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{application}\n",
        ),
    )

    assert _source_checkout_revision(package) is None


def test_installed_revision_falls_back_to_distribution_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(revision_module, "_source_checkout_revision", lambda _path: None)
    monkeypatch.setattr(revision_module, "version", lambda _name: "9.8.7")

    assert installed_llm_client_revision() == "package:9.8.7"


def test_configured_revision_mismatch_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        revision_module,
        "installed_llm_client_revision",
        lambda: "a" * 40,
    )

    with pytest.raises(ValueError, match="does not match installed llm_client revision"):
        validated_llm_client_revision("b" * 40)


def test_matching_configured_revision_returns_installed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        revision_module,
        "installed_llm_client_revision",
        lambda: "a" * 40,
    )

    assert validated_llm_client_revision("a" * 40) == "a" * 40
