#!/bin/bash
# Check if a hook is enabled in meta-process.yaml
#
# Usage (source this in other hooks):
#   source "$(dirname "$0")/check-hook-enabled.sh"
#   if ! is_hook_enabled "protect_main"; then
#       exit 0  # Hook disabled, skip
#   fi
#
# Or check directly:
#   ./check-hook-enabled.sh protect_main  # exits 0 if enabled

# Get repo root
get_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$(dirname "$0")")"
}

# Check if a hook is enabled.
# Returns 0 when enabled, 1 when disabled, and 2 for invalid configuration.
is_hook_enabled() {
    local hook_name="$1"
    local repo_root
    repo_root=$(get_repo_root)

    # Use Python helper if available (more reliable YAML parsing)
    if [[ -f "$repo_root/scripts/meta_config.py" ]]; then
        python "$repo_root/scripts/meta_config.py" --hook "$hook_name" 2>/dev/null
        return $?
    fi

    local config_file="$repo_root/meta-process.yaml"
    if [[ ! -f "$config_file" ]]; then
        return 1
    fi

    "${PYTHON:-python3}" - "$config_file" "$hook_name" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
hook_name = sys.argv[2]
try:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    meta_process = raw.get("meta_process", {})
    if not isinstance(meta_process, dict):
        raise ValueError("meta_process must be a mapping")
    worktrees = meta_process.get("worktrees", {})
    if not isinstance(worktrees, dict):
        raise ValueError("meta_process.worktrees must be a mapping")
    explicit_hooks = meta_process.get("hooks", {})
    if not isinstance(explicit_hooks, dict):
        raise ValueError("meta_process.hooks must be a mapping")
except (OSError, ValueError, yaml.YAMLError) as exc:
    print(f"ERROR: cannot resolve hook mode from {config_path}: {exc}", file=sys.stderr)
    raise SystemExit(2)

resolved = {
    "protect_main": bool(worktrees.get("protect_main", False)),
    "enforce_workflow": bool(worktrees.get("enabled", False)),
    "warn_worktree_cwd": bool(worktrees.get("enabled", False)),
}.get(hook_name, bool(explicit_hooks.get(hook_name, False)))
raise SystemExit(0 if resolved else 1)
PY
}

# If called directly (not sourced), check the hook
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ -z "$1" ]]; then
        echo "Usage: $0 <hook_name>" >&2
        exit 1
    fi
    is_hook_enabled "$1"
    exit $?
fi
