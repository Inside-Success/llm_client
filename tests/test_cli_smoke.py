from __future__ import annotations

import subprocess
import sys


CLI_CMDS = [
    ["--help"],
    ["cost", "--help"],
    ["traces", "--help"],
    ["scores", "--help"],
    ["experiments", "--help"],
    ["adoption", "--help"],
    ["backfill", "--help"],
    ["tool-lint", "--help"],
    ["tool-usage", "--help"],
    ["tool-usage", "import", "--help"],
    ["tool-usage", "report", "--help"],
    ["review-artifact", "--help"],
    ["review-cycle", "--help"],
    ["duet-review", "--help"],
    ["deliberate-task", "--help"],
    ["provider-limit", "--help"],
    ["provider-limit", "openrouter", "--help"],
    ["json-schema-call", "--help"],
]


def test_cli_help_smoke() -> None:
    for cmd in CLI_CMDS:
        proc = subprocess.run(
            [sys.executable, "-m", "llm_client", *cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"command failed: {cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        assert "usage:" in proc.stdout.lower()
