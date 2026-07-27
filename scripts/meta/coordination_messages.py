#!/usr/bin/env python3
"""Run the canonical coordination mailbox CLI from an installed governed repo."""

from __future__ import annotations

import runpy
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "coordination_messages.py"
if not SOURCE.is_file():
    raise RuntimeError(f"Installed coordination message entrypoint is missing: {SOURCE}")
runpy.run_path(str(SOURCE), run_name="__main__")
