"""Unit tests for the ``review-artifact`` CLI command.

Tests cover schema construction, prompt assembly, and CLI argparse plumbing.
The live LLM call is exercised separately via integration tests (see
``tests/test_workflow_schema_smoke.py`` for the pattern).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_client.cli.review_artifact import (
    _adversarial_review_schema,
    _resolve_artifact,
    _resolve_context,
    _review_prompt,
)


def test_schema_builds_with_required_fields() -> None:
    schema = _adversarial_review_schema()
    instance = schema(
        artifact_label="slice 12",
        verdict="pass",
        summary="LGTM",
    )
    assert instance.artifact_label == "slice 12"
    assert instance.verdict == "pass"
    assert instance.correctness_findings == []
    assert instance.contract_violations == []


def test_schema_rejects_extra_fields() -> None:
    schema = _adversarial_review_schema()
    with pytest.raises(Exception):  # pydantic ValidationError
        schema(
            artifact_label="x",
            verdict="pass",
            summary="x",
            extra_field="not allowed",
        )


def test_schema_rejects_invalid_verdict() -> None:
    schema = _adversarial_review_schema()
    with pytest.raises(Exception):
        schema(artifact_label="x", verdict="LGTM", summary="x")


def test_review_prompt_includes_artifact_and_context() -> None:
    schema = _adversarial_review_schema()
    msgs = _review_prompt(
        artifact_label="my-feature.py",
        artifact_body="def foo(): return 42",
        context_body="Adding the foo helper for caller X",
        response_schema=schema,
    )
    assert len(msgs) == 2
    user = msgs[1]["content"]
    assert "my-feature.py" in user
    assert "def foo(): return 42" in user
    assert "Adding the foo helper for caller X" in user
    assert "## Context" in user


def test_review_prompt_handles_missing_context() -> None:
    schema = _adversarial_review_schema()
    msgs = _review_prompt(
        artifact_label="x",
        artifact_body="content",
        context_body="",
        response_schema=schema,
    )
    assert "(no context provided" in msgs[1]["content"]


def test_review_prompt_adversarial_framing() -> None:
    """The system prompt must explicitly frame the reviewer adversarially."""
    schema = _adversarial_review_schema()
    msgs = _review_prompt("x", "y", "z", schema)
    system = msgs[0]["content"]
    assert "adversarial" in system.lower()
    assert "wrong" in system.lower() or "bias" in system.lower()


def test_resolve_artifact_from_file(tmp_path: Path) -> None:
    f = tmp_path / "art.py"
    f.write_text("hello\n")
    args = MagicMock(
        artifact_file=str(f),
        artifact_text=None,
        artifact_label="custom-label",
    )
    label, body = _resolve_artifact(args)
    assert label == "custom-label"
    assert body == "hello\n"


def test_resolve_artifact_from_text() -> None:
    args = MagicMock(
        artifact_file=None,
        artifact_text="inline body",
        artifact_label="",
    )
    label, body = _resolve_artifact(args)
    assert label == "(inline)"
    assert body == "inline body"


def test_resolve_artifact_falls_back_to_filename(tmp_path: Path) -> None:
    f = tmp_path / "slice-12.patch"
    f.write_text("diff --git ...\n")
    args = MagicMock(
        artifact_file=str(f),
        artifact_text=None,
        artifact_label="",
    )
    label, _ = _resolve_artifact(args)
    assert label == "slice-12.patch"


def test_resolve_artifact_missing_file_exits(tmp_path: Path) -> None:
    args = MagicMock(
        artifact_file=str(tmp_path / "nope.py"),
        artifact_text=None,
        artifact_label="",
    )
    with pytest.raises(SystemExit):
        _resolve_artifact(args)


def test_resolve_artifact_no_input_exits() -> None:
    args = MagicMock(artifact_file=None, artifact_text=None, artifact_label="")
    with pytest.raises(SystemExit):
        _resolve_artifact(args)


def test_resolve_context_empty_when_neither_provided() -> None:
    args = MagicMock(context_file=None, context_text=None)
    assert _resolve_context(args) == ""


def test_resolve_context_from_file(tmp_path: Path) -> None:
    f = tmp_path / "ctx.md"
    f.write_text("context body\n")
    args = MagicMock(context_file=str(f), context_text=None)
    assert _resolve_context(args) == "context body\n"
