"""``review-artifact``: standalone adversarial review of a single artifact.

Designed for the fire-and-forget pattern: a working agent finishes a slice
(commit, plan doc, code diff, decision), spawns ``review-artifact`` in the
background, and keeps working on the next slice. The review JSON appears at
``--out`` when the reviewer finishes; the foreground agent integrates the
findings at the next natural checkpoint.

Distinct from ``duet-review``, which expects ``--plan-doc`` + ``--impl-base``
+ ``--task-family`` ceremony. This command takes any artifact (text, file, or
diff) plus optional context and emits a structured review. Reuses the typed
finding shapes (``CorrectnessFinding``, ``ContractViolation``, ``Nit``,
``UnverifiedClaim``) from the duet so downstream consumers can treat duet
reviews and standalone reviews uniformly.

Usage::

    # Foreground: agent finishes a slice
    git diff HEAD~1 > /tmp/slice-12.patch

    # Background: kick off adversarial review (returns immediately under &)
    python -m llm_client review-artifact \\
        --artifact-file /tmp/slice-12.patch \\
        --artifact-label "slice 12: barrier topology" \\
        --context-text "Implementing Plan #35 barrier semantics; the agent_b prompt must not see agent_a freshest round-N output." \\
        --reviewer claude-code/sonnet \\
        --workspace /path/to/repo \\
        --out /tmp/review-slice-12.json &

    # Keep working in the foreground while the review runs...
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from llm_client.workflow.adversarial_review import (
    adversarial_review_schema,
    adversarial_review_response_schema,
    build_review_prompt,
    get_review_profile,
    normalize_adversarial_review_response,
    render_quality_optimal_sections,
    resolve_review_schema_version,
)


def _adversarial_review_schema():
    """Compatibility shim for callers that imported the old CLI helper."""
    return adversarial_review_schema("1")


def _review_prompt(
    artifact_label: str,
    artifact_body: str,
    context_body: str,
    response_schema: type,
) -> list[dict[str, Any]]:
    """Compatibility shim for callers that imported the old CLI helper."""
    return build_review_prompt(
        artifact_label=artifact_label,
        artifact_body=artifact_body,
        context_body=context_body,
        response_schema=response_schema,
    )


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------


def _resolve_artifact(args: argparse.Namespace) -> tuple[str, str]:
    """Return (artifact_label, artifact_body)."""
    if args.artifact_file:
        path = Path(args.artifact_file).resolve()
        if not path.is_file():
            print(f"error: --artifact-file not found: {path}", file=sys.stderr)
            sys.exit(2)
        label = args.artifact_label or path.name
        return label, path.read_text(encoding="utf-8")
    if args.artifact_text is not None:
        return args.artifact_label or "(inline)", args.artifact_text
    print("error: must pass --artifact-file or --artifact-text", file=sys.stderr)
    sys.exit(2)


def _resolve_context(args: argparse.Namespace) -> str:
    if args.context_file:
        path = Path(args.context_file).resolve()
        if not path.is_file():
            print(f"error: --context-file not found: {path}", file=sys.stderr)
            sys.exit(2)
        return path.read_text(encoding="utf-8")
    if args.context_text is not None:
        return args.context_text
    return ""


def cmd_review_artifact(args: argparse.Namespace) -> None:
    """Execute the ``review-artifact`` subcommand."""
    from llm_client import call_llm_structured  # type: ignore[attr-defined]

    artifact_label, artifact_body = _resolve_artifact(args)
    context_body = _resolve_context(args)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    workspace = str(Path(args.workspace).resolve()) if args.workspace else None
    task_id = args.task_id or f"review-{int(time.time())}"

    profile = get_review_profile(args.review_profile)
    schema_version = resolve_review_schema_version(profile, args.review_schema_version)
    schema = adversarial_review_schema(schema_version)
    response_schema = adversarial_review_response_schema(schema_version)
    messages = build_review_prompt(
        artifact_label=artifact_label,
        artifact_body=artifact_body,
        context_body=context_body,
        response_schema=schema,
        profile=profile,
    )

    print(
        f"=== adversarial review ({args.reviewer}, artifact={artifact_label!r}) ===",
        flush=True,
    )
    review, _meta = call_llm_structured(
        args.reviewer,
        messages,
        response_schema,
        task="review_artifact",
        trace_id=f"{task_id}/review",
        max_budget=args.max_budget,
        timeout=args.timeout,
        yolo_mode=True,
        cwd=workspace,
    )
    review = normalize_adversarial_review_response(review)

    payload = review.model_dump()
    payload["reviewer_model"] = args.reviewer
    if schema_version == "1":
        payload.pop("profile_annotations", None)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"  verdict: {payload['verdict']}")
    print(
        f"  correctness: {len(payload['correctness_findings'])}, "
        f"contract: {len(payload['contract_violations'])}, "
        f"nits: {len(payload['nits'])}, "
        f"unverified: {len(payload['unverified_claims'])}, "
        f"scope_drift: {len(payload['scope_drift_findings'])}"
    )
    if profile.name == "quality_optimal_whitepaper":
        rendered_path = out_path.with_suffix(".md")
        rendered_path.write_text(render_quality_optimal_sections(review), encoding="utf-8")
        print(f"  rendered to {rendered_path}")
    print(f"  written to {out_path}")


def register_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "review-artifact",
        help="Standalone adversarial review of an arbitrary artifact "
             "(designed for background fire-and-forget use).",
    )
    p.add_argument(
        "--artifact-file",
        help="Path to the artifact to review (diff, code, plan doc, decision text).",
    )
    p.add_argument(
        "--artifact-text",
        help="Inline artifact text (use instead of --artifact-file for short content).",
    )
    p.add_argument(
        "--artifact-label",
        default="",
        help="Human-readable label for the artifact (defaults to filename or '(inline)').",
    )
    p.add_argument(
        "--context-file",
        help="Path to a context document describing what the author was attempting.",
    )
    p.add_argument(
        "--context-text",
        help="Inline context text.",
    )
    p.add_argument(
        "--reviewer",
        default="claude-code/sonnet",
        help="Reviewer model (default: claude-code/sonnet).",
    )
    p.add_argument(
        "--review-profile",
        default="generic",
        help="Review profile to use (default: generic).",
    )
    p.add_argument(
        "--review-schema-version",
        choices=["auto", "1", "2"],
        default="auto",
        help="AdversarialReview schema version (default: auto).",
    )
    p.add_argument(
        "--workspace",
        help="Workspace path for the reviewer's file-reading tools (cwd).",
    )
    p.add_argument(
        "--task-id",
        help="Task ID for trace_id (default: review-<unix_ts>).",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output JSON path for the AdversarialReview.",
    )
    p.add_argument(
        "--max-budget",
        type=float,
        default=2.0,
        help="Per-call max budget USD (default: 2.0).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1500.0,
        help="Per-call timeout seconds (default: 1500). claude-code reviewers "
             "with workspace tool access routinely exceed 600s on non-trivial "
             "artifacts; bump higher for large diffs.",
    )
    p.set_defaults(handler=cmd_review_artifact)
