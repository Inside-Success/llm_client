#!/bin/bash
# Codex PreToolUse/apply_patch adapter for exact claim ownership.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON="python3"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
fi

exec "$PYTHON" "$REPO_ROOT/scripts/prewrite_claim_gate.py" --client codex
