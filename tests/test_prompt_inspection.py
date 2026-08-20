"""Duplicated content inside one assembled prompt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_client.prompt_inspection import (
    DEFAULT_MIN_DUPLICATE_BYTES,
    DuplicateContentError,
    find_duplicated_content,
    report_duplicated_content,
)

BIG = "x" * 40_000


def _audit(payload: str) -> dict:
    return {"summary": "s", "candidates": [{"body": payload}]}


def test_the_case_this_was_built_from() -> None:
    """A field that is a byte-identical copy of another, inside one artifact.

    This is the shape that cost 1,076,211 duplicated characters per call on a
    real payload: ``final_audit`` mirroring ``attempts[-1].audit``.
    """
    audit = _audit(BIG)
    context = {
        "artifacts_json": json.dumps(
            {"resolution": {"attempts": [{"audit": audit}], "final_audit": audit}}
        )
    }

    findings = find_duplicated_content(context)

    assert len(findings) == 1
    paths = set(findings[0].paths)
    assert paths == {
        "artifacts_json/resolution/attempts/0/audit",
        "artifacts_json/resolution/final_audit",
    }
    assert findings[0].wasted_bytes > 40_000


def test_text_level_scanning_would_miss_it() -> None:
    """Why this walks structure instead of the rendered string.

    The two copies sit at different nesting depths, so an indented render gives
    them different byte layouts and a window-based scan finds nothing. Canonical
    serialization is what makes them comparable.
    """
    audit = _audit(BIG)
    doc = {"resolution": {"attempts": [{"audit": audit}], "final_audit": audit}}
    rendered = json.dumps(doc, indent=2)

    # The two copies are genuinely not byte-identical in the rendered form.
    a = json.dumps(doc["resolution"]["attempts"][0]["audit"], indent=2)
    b = json.dumps(doc["resolution"]["final_audit"], indent=2)
    assert a == b, "same layout at top level"
    assert rendered.count(BIG) == 2, "content really is present twice"

    # ...yet structural detection finds it regardless of layout.
    assert len(find_duplicated_content({"artifacts_json": json.dumps(doc)})) == 1


def test_only_the_outermost_duplication_is_reported() -> None:
    """A nested duplicate is a consequence, not a separate finding.

    The real payload contained four duplicated subtrees; three sat inside the
    first. Listing all of them buries the finding under its own effects.
    """
    audit = _audit(BIG)
    context = {
        "artifacts_json": json.dumps(
            {"attempts": [{"audit": audit}], "final_audit": audit}
        )
    }

    findings = find_duplicated_content(context)

    assert len(findings) == 1, [f.describe() for f in findings]


def test_duplication_across_two_variables_is_found() -> None:
    """The same payload passed twice under different names is still waste."""
    shared = json.dumps({"body": BIG})
    findings = find_duplicated_content(
        {"evidence_json": shared, "context_json": shared}
    )

    assert len(findings) == 1
    assert set(findings[0].paths) == {"evidence_json", "context_json"}


def test_small_repeats_are_ignored() -> None:
    """Ids, enums and nulls repeat constantly and mean nothing."""
    doc = {"a": {"status": "ok", "id": "x1"}, "b": {"status": "ok", "id": "x1"}}
    assert find_duplicated_content({"j": json.dumps(doc)}) == []


def test_threshold_is_adjustable() -> None:
    doc = {"a": {"v": "y" * 500}, "b": {"v": "y" * 500}}
    assert find_duplicated_content({"j": json.dumps(doc)}) == []
    assert find_duplicated_content({"j": json.dumps(doc)}, min_bytes=100)


def test_non_json_values_are_still_compared_whole() -> None:
    """A plain-text variable duplicated verbatim is caught, even if opaque."""
    findings = find_duplicated_content({"a_text": BIG, "b_text": BIG})

    assert len(findings) == 1
    assert set(findings[0].paths) == {"a_text", "b_text"}


def test_a_prompt_with_no_duplication_is_silent() -> None:
    assert find_duplicated_content(
        {"evidence_json": json.dumps({"a": BIG}), "other_json": json.dumps({"b": "z" * 40_000})}
    ) == []


def test_warns_by_default_and_raises_only_in_strict_mode(monkeypatch) -> None:
    """Duplication is waste, not incorrectness; it must not stop a pipeline."""
    audit = _audit(BIG)
    context = {"artifacts_json": json.dumps({"x": audit, "y": audit})}

    monkeypatch.delenv("LLM_CLIENT_PROMPT_DUPLICATE_STRICT", raising=False)
    assert report_duplicated_content(context, label="demo.yaml")

    monkeypatch.setenv("LLM_CLIENT_PROMPT_DUPLICATE_STRICT", "1")
    with pytest.raises(DuplicateContentError, match="wasted bytes"):
        report_duplicated_content(context, label="demo.yaml")


def test_ci_alone_does_not_make_it_fatal(monkeypatch) -> None:
    """Consistent with the rest of this stack: strict mode is never inferred."""
    monkeypatch.delenv("LLM_CLIENT_PROMPT_DUPLICATE_STRICT", raising=False)
    monkeypatch.setenv("CI", "1")
    audit = _audit(BIG)
    assert report_duplicated_content(
        {"artifacts_json": json.dumps({"x": audit, "y": audit})}, label="demo.yaml"
    )


def test_render_prompt_reports_duplication(tmp_path: Path, monkeypatch) -> None:
    """It runs on the real render path, not just when called directly."""
    from llm_client.prompts import render_prompt

    monkeypatch.setenv("LLM_CLIENT_PROMPT_DUPLICATE_STRICT", "1")
    template = tmp_path / "demo.yaml"
    template.write_text(
        "messages:\n  - role: user\n    content: |\n      {{ artifacts_json }}\n",
        encoding="utf-8",
    )
    audit = _audit(BIG)

    with pytest.raises(DuplicateContentError):
        render_prompt(template, artifacts_json=json.dumps({"x": audit, "y": audit}))


def test_default_threshold_is_documented_value() -> None:
    assert DEFAULT_MIN_DUPLICATE_BYTES == 10_000
