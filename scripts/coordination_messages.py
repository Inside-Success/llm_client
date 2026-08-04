#!/usr/bin/env python3
"""Run the package-backed cross-client coordination mailbox CLI."""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_package() -> None:
    """Load a local installed package or the target repo's upstream bootstrap."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            scripts_dir = helper.parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    raise RuntimeError(
        "Unable to locate a local enforced_planning package or scripts/_upstream_enforced_planning.py"
    )


_bootstrap_package()

from enforced_planning.coordination_messages import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
