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
        --reviewer claude-code/opus \\
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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Output schema (reuses typed finding shapes from llm_client.workflow.duet)
# ---------------------------------------------------------------------------

AdversarialVerdict = Literal["pass", "concerns", "blocker"]


def _adversarial_review_schema():
    """Build the AdversarialReview schema lazily so this module loads
    without forcing langgraph/workflow imports at process start."""
    from llm_client.workflow.duet import (
        ContractViolation,
        CorrectnessFinding,
        Nit,
        UnverifiedClaim,
    )

    class AdversarialReview(BaseModel):
        """Output of a standalone adversarial review.

        Verdict semantics:
        - ``pass``: no blockers; nits/unverified-claims may still appear but
          the artifact is shippable as-is.
        - ``concerns``: blockers or contract violations exist; integrate before
          shipping.
        - ``blocker``: at least one high-severity correctness or contract
          finding; do not ship until resolved.
        """

        model_config = ConfigDict(extra="forbid")

        artifact_label: str
        verdict: AdversarialVerdict
        summary: str
        correctness_findings: list[CorrectnessFinding] = Field(default_factory=list)
        contract_violations: list[ContractViolation] = Field(default_factory=list)
        nits: list[Nit] = Field(default_factory=list)
        unverified_claims: list[UnverifiedClaim] = Field(default_factory=list)
        scope_drift_findings: list[str] = Field(default_factory=list)
        reviewer_model: str = ""

    return AdversarialReview


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _review_prompt(
    artifact_label: str,
    artifact_body: str,
    context_body: str,
    response_schema: type,
) -> list[dict[str, Any]]:
    system = (
        "You are an adversarial reviewer. Your job is to find what's WRONG "
        "with the artifact below, not to validate it. The author of the "
        "artifact is biased toward their own work; your role is the opposite "
        "bias — look for bugs, missed edge cases, contradictions with stated "
        "constraints, unverifiable claims, and scope drift. Inspect the "
        "workspace via your file-reading tools to verify any claim against "
        "actual code. Do not edit any files."
    )

    user_parts = [
        f"## Artifact under review: {artifact_label}",
        "",
        "## Context (what the author was attempting)",
        context_body or "(no context provided — review on intrinsic merit)",
        "",
        "## Artifact body",
        artifact_body,
        "",
        "Return an AdversarialReview JSON object. Verdict must be one of: "
        "pass, concerns, blocker. Groundedness rules: every "
        "correctness_findings entry MUST have file_path (str) and line (int); "
        "every contract_violations entry MUST have constraint, violation, "
        "and evidence_path. If you cannot cite a specific file:line, use "
        "unverified_claims (UnverifiedClaim with claim + reason_unverified) "
        "or a free-text scope_drift_findings entry instead. Use 'blocker' "
        "verdict only when at least one finding would break correctness or "
        "a stated constraint. Use 'concerns' when there are blockers or "
        "contract violations but they're not catastrophic. Use 'pass' when "
        "the artifact is shippable as-is (nits/unverified may still appear).",
    ]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


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

    schema = _adversarial_review_schema()
    messages = _review_prompt(artifact_label, artifact_body, context_body, schema)

    print(
        f"=== adversarial review ({args.reviewer}, artifact={artifact_label!r}) ===",
        flush=True,
    )
    review, _meta = call_llm_structured(
        args.reviewer,
        messages,
        schema,
        task="review_artifact",
        trace_id=f"{task_id}/review",
        max_budget=args.max_budget,
        timeout=args.timeout,
        yolo_mode=True,
        cwd=workspace,
    )

    payload = review.model_dump()
    payload["reviewer_model"] = args.reviewer
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"  verdict: {payload['verdict']}")
    print(
        f"  correctness: {len(payload['correctness_findings'])}, "
        f"contract: {len(payload['contract_violations'])}, "
        f"nits: {len(payload['nits'])}, "
        f"unverified: {len(payload['unverified_claims'])}, "
        f"scope_drift: {len(payload['scope_drift_findings'])}"
    )
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
        default="claude-code/opus",
        help="Reviewer model (default: claude-code/opus).",
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
