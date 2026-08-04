#!/usr/bin/env python3
"""CLI wrapper for bounded relationship-aware edit context packets."""

from __future__ import annotations

from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if SCRIPT_PATH.parent.name == "meta" else SCRIPT_PATH.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.context_packet import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
