#!/usr/bin/env python3
"""Atomically refresh the derived pre-write authority projection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.prewrite_claim_fast import DEFAULT_CLAIMS_DIR  # noqa: E402
from enforced_planning.prewrite_claim_projection import write_projection  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--projection-path", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    projection = write_projection(
        claims_dir=args.claims_dir,
        projection_path=args.projection_path,
    )
    if args.json:
        print(projection.model_dump_json(indent=2))
    else:
        print(
            "Refreshed pre-write authority projection: "
            f"claims={len(projection.claims)} digest={projection.registry_digest}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
