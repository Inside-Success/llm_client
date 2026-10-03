"""The doc-authority validator fails loudly, not with a traceback, when unconfigured."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "meta" / "validate_doc_authority.py"


def test_missing_config_exits_2_with_message(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--repo-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "doc-authority config not found" in proc.stderr
    assert "Traceback" not in proc.stderr
