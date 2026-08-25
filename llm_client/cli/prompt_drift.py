"""Prompt-size drift CLI command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from llm_client.observability.prompt_drift import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_DISPERSION_RATIO,
    DEFAULT_GROWTH_RATIO,
    DEFAULT_MIN_CALLS,
    DEFAULT_RECENT_DAYS,
    find_prompt_drift,
)


def _render_table(findings: list[Any]) -> str:
    header = (
        f"{'project':22} {'task':44} {'base med':>10} {'recent med':>11} "
        f"{'recent max':>11} {'growth':>7} {'disp':>6}  reasons"
    )
    lines = [header, "-" * len(header)]
    for f in findings:
        growth = f"{f.growth_ratio:.1f}x" if f.growth_ratio is not None else "-"
        base = (
            f"{f.baseline_median_prompt_tokens:,.0f}"
            if f.baseline_median_prompt_tokens is not None
            else "no base"
        )
        disp = f"{f.dispersion_ratio:.1f}x" if f.dispersion_ratio is not None else "-"
        lines.append(
            f"{str(f.project)[:22]:22} {f.task[:44]:44} "
            f"{base:>10} "
            f"{f.recent_median_prompt_tokens:11,.0f} "
            f"{f.recent_max_prompt_tokens:11,} "
            f"{growth:>7} {disp:>6}  {','.join(f.reasons)}"
        )
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> None:
    findings = find_prompt_drift(
        baseline_days=args.baseline_days,
        recent_days=args.recent_days,
        min_calls=args.min_calls,
        growth_ratio=args.growth_ratio,
        dispersion_ratio=args.dispersion_ratio,
        project=args.project,
        task=args.task,
    )

    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=2))
    elif not findings:
        print("No prompt-size drift detected against the configured thresholds.")
    else:
        print(_render_table(findings))
        print(
            f"\n{len(findings)} task(s) drifted. Prompt tokens, not cost: caching "
            "can make a larger payload bill less than a smaller one."
        )

    if args.fail_on_drift and findings:
        sys.exit(1)


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "prompt-drift",
        help="Detect tasks whose prompt size grew past their own baseline",
    )
    parser.add_argument("--baseline-days", type=int, default=DEFAULT_BASELINE_DAYS)
    parser.add_argument("--recent-days", type=int, default=DEFAULT_RECENT_DAYS)
    parser.add_argument("--min-calls", type=int, default=DEFAULT_MIN_CALLS)
    parser.add_argument("--growth-ratio", type=float, default=DEFAULT_GROWTH_RATIO)
    parser.add_argument("--dispersion-ratio", type=float, default=DEFAULT_DISPERSION_RATIO)
    parser.add_argument("--project", default=None)
    parser.add_argument("--task", default=None)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit 1 when any drift is found (for CI gates)",
    )
    parser.set_defaults(handler=_run)
