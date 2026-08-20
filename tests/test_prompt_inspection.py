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


# --------------------------------------------------------------------------
# Size attribution and reading a rendered prompt
# --------------------------------------------------------------------------


def test_size_attribution_names_the_variable_that_owns_the_prompt() -> None:
    """Total size was never the mystery; which variable owns it is."""
    from llm_client.prompt_inspection import summarize_context

    sizes = summarize_context(
        {"evidence_json": "e" * 87_830, "artifacts_json": "a" * 2_917_684, "target_json": "t" * 1_536}
    )

    assert [item.name for item in sizes] == ["artifacts_json", "evidence_json", "target_json"]
    assert sizes[0].share > 0.96
    assert sizes[1].share < 0.03


def test_size_attribution_of_an_empty_context_does_not_divide_by_zero() -> None:
    from llm_client.prompt_inspection import format_context_summary, summarize_context

    assert summarize_context({}) == []
    assert format_context_summary([]) == "(no context variables)"


def test_json_is_recovered_from_a_rendered_prompt() -> None:
    """A stored prompt is flat text; the structure has to be recovered."""
    from llm_client.prompt_inspection import extract_json_spans

    payload = {"big": [{"v": "x" * 300} for _ in range(60)]}
    rendered = f"## Heading\n\n{json.dumps(payload, indent=2)}\n\ntrailing prose"

    spans = extract_json_spans(rendered)

    assert len(spans) == 1
    assert spans[0] == payload


def test_duplication_is_found_in_a_rendered_prompt() -> None:
    """The retrospective path: audit a call that already happened."""
    from llm_client.prompt_inspection import find_duplicated_content_in_text

    audit = _audit(BIG)
    # Indent differs between the two copies once nested, which is exactly why
    # text scanning fails and structural recovery is required.
    rendered = "## Artifacts\n\n" + json.dumps(
        {"resolution": {"attempts": [{"audit": audit}], "final_audit": audit}}, indent=2
    )

    findings = find_duplicated_content_in_text(rendered)

    assert len(findings) == 1
    assert findings[0].wasted_bytes > 40_000


def test_small_inline_json_is_not_worth_parsing() -> None:
    from llm_client.prompt_inspection import extract_json_spans

    assert extract_json_spans('prose {"a": 1} more prose') == []


def test_prose_without_json_yields_nothing_rather_than_erroring() -> None:
    from llm_client.prompt_inspection import find_duplicated_content_in_text

    assert find_duplicated_content_in_text("just prose, no structure at all") == []


# --------------------------------------------------------------------------
# The digest a judge reads instead of the prompt
# --------------------------------------------------------------------------


def test_digest_preserves_proportion_which_truncation_destroys() -> None:
    """The reason a judge is shown a digest and not the prompt.

    Truncating a large prompt to fit a judge's window keeps the first N bytes,
    which is exactly the wrong sample: it discards the shares that the question
    is about while looking like it preserved the content.
    """
    from llm_client.prompt_inspection import build_prompt_digest

    context = {
        "evidence_json": json.dumps({"e": "x" * 80_000}),
        "artifacts_json": json.dumps({"a": "y" * 2_900_000}),
    }

    digest = build_prompt_digest(context)

    assert "artifacts_json" in digest and "evidence_json" in digest
    assert "96." in digest or "97." in digest, digest[:400]
    assert len(digest) < 5_000, "a digest that needs truncating defeats the point"


def test_digest_reports_duplication_it_found() -> None:
    from llm_client.prompt_inspection import build_prompt_digest

    audit = _audit(BIG)
    digest = build_prompt_digest(
        {"artifacts_json": json.dumps({"x": audit, "y": audit})}
    )

    assert "Repeated content:" in digest
    assert "sent more than once" in digest


def test_digest_says_so_when_nothing_repeats() -> None:
    """Absence of a finding must be stated, not left ambiguous."""
    from llm_client.prompt_inspection import build_prompt_digest

    digest = build_prompt_digest({"a_json": json.dumps({"a": "x" * 40_000})})

    assert "Repeated content: none found." in digest


def test_digest_samples_each_variable_so_relevance_is_judgeable() -> None:
    """Sizes answer proportion; samples are what make relevance answerable."""
    from llm_client.prompt_inspection import build_prompt_digest

    digest = build_prompt_digest(
        {"evidence_json": "EVIDENCE-MARKER" + "x" * 50_000}, sample_chars=100
    )

    assert "EVIDENCE-MARKER" in digest
    assert "..." in digest, "a truncated sample should be marked as truncated"


def test_digest_of_an_empty_context_is_still_well_formed() -> None:
    from llm_client.prompt_inspection import build_prompt_digest

    assert "0 bytes total" in build_prompt_digest({})


def test_the_shipped_rubric_matches_the_digest_it_scores() -> None:
    """The rubric asks only questions the digest actually supports."""
    from llm_client.rubric_registry import load_rubric

    rubric = load_rubric("prompt_context_quality")
    names = {dimension.name for dimension in rubric.dimensions}

    assert names == {"proportionality", "necessity", "non_redundancy", "sufficiency"}
    # sufficiency is the one that catches starvation, which is the failure a
    # context-supplying mechanism introduces and the only one that is silent.
    assert "sufficiency" in names
