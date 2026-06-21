#!/usr/bin/env bash
# auto_adversarial_review_hook.sh — Claude Code Stop hook
#
# Fires when the agent ends a turn. If the agent's final message contains
# the trigger phrase ("ready for review" by default), captures the latest
# git diff or HEAD commit as the artifact and spawns an adversarial
# `python -m llm_client review-artifact` against the OTHER model
# (codex/gpt-5.4 by default; a parallel Codex Stop hook can mirror this
# with claude-code/opus as the reviewer when Codex stops).
#
# Inputs (JSON on stdin from Claude Code):
#   session_id          — current session ID
#   transcript_path     — path to session JSONL transcript
#   cwd                 — working directory
#   stop_hook_active    — true if we're already inside a hook chain
#
# Behavior:
#   - Skip if stop_hook_active=true (prevents infinite loops)
#   - Skip if no trigger phrase in the last assistant message
#   - Skip if no diff to review
#   - Skip if cwd is not inside a git repo
#   - Otherwise spawn review-artifact in background; review lands at
#     runs/auto-review/<timestamp>-review.json and is indexed in INDEX.md
#
# Config (env vars):
#   AUTO_REVIEW_TRIGGER       — phrase to look for (default: "ready for review")
#   AUTO_REVIEW_REVIEWER      — reviewer model (default: codex/gpt-5.4)
#   AUTO_REVIEW_MIN_LOC       — minimum LOC changed to trigger (default: 5)
#   AUTO_REVIEW_DISABLED      — set to "1" to disable entirely
#
# Wiring: add to ~/.claude/settings.json or a project .claude/settings.json
#   {
#     "hooks": {
#       "Stop": [
#         {"hooks": [{"type": "command",
#           "command": "/abs/path/to/auto_adversarial_review_hook.sh"}]}
#       ]
#     }
#   }
set -euo pipefail

input="$(cat)"

# ---------------------------------------------------------------------------
# Bail-out checks. Stop hooks should never interrupt the stop event, so all
# failure paths exit 0 silently.
# ---------------------------------------------------------------------------

[[ "${AUTO_REVIEW_DISABLED:-0}" == "1" ]] && exit 0

stop_hook_active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false')"
[[ "$stop_hook_active" == "true" ]] && exit 0

transcript_path="$(printf '%s' "$input" | jq -r '.transcript_path // ""')"
cwd="$(printf '%s' "$input" | jq -r '.cwd // ""')"

[[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0
[[ -z "$cwd" || ! -d "$cwd" ]] && exit 0

git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1 || exit 0

# ---------------------------------------------------------------------------
# Trigger-phrase check on the last assistant message.
# ---------------------------------------------------------------------------

trigger="${AUTO_REVIEW_TRIGGER:-ready for review}"

last_assistant_text="$(
  tac "$transcript_path" \
    | jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' 2>/dev/null \
    | head -200
)"

[[ -z "$last_assistant_text" ]] && exit 0
printf '%s' "$last_assistant_text" | grep -qiF "$trigger" || exit 0

# ---------------------------------------------------------------------------
# Resolve the artifact: prefer working-tree diff, fall back to HEAD commit.
# ---------------------------------------------------------------------------

min_loc="${AUTO_REVIEW_MIN_LOC:-5}"
artifact_tmp="$(mktemp -t auto-review-artifact-XXXXXX.patch)"
artifact_kind=""

if ! git -C "$cwd" diff --quiet 2>/dev/null \
   || ! git -C "$cwd" diff --cached --quiet 2>/dev/null; then
  git -C "$cwd" diff HEAD > "$artifact_tmp" 2>/dev/null || true
  artifact_kind="working-tree"
else
  git -C "$cwd" show HEAD > "$artifact_tmp" 2>/dev/null || true
  artifact_kind="head-commit"
fi

if [[ ! -s "$artifact_tmp" ]]; then
  rm -f "$artifact_tmp"
  exit 0
fi

loc_changed="$(grep -E '^[-+][^-+]' "$artifact_tmp" 2>/dev/null | wc -l || echo 0)"
if [[ "$loc_changed" -lt "$min_loc" ]]; then
  rm -f "$artifact_tmp"
  exit 0
fi

# ---------------------------------------------------------------------------
# Spawn review-artifact in background. Output lands under
# runs/auto-review/<timestamp>.json; INDEX.md tracks pending reviews.
# ---------------------------------------------------------------------------

reviewer="${AUTO_REVIEW_REVIEWER:-codex/gpt-5.4}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="$cwd/runs/auto-review"
mkdir -p "$out_dir"

artifact_path="$out_dir/${ts}-artifact.patch"
context_path="$out_dir/${ts}-context.md"
review_path="$out_dir/${ts}-review.json"
log_path="$out_dir/${ts}-stderr.log"

mv "$artifact_tmp" "$artifact_path"

{
  printf '# Auto-review context (%s)\n\n' "$ts"
  printf '## Artifact source\n%s\n\n' "$artifact_kind"
  printf '## Trigger phrase matched\n%s\n\n' "$trigger"
  printf '## Agent final narrative\n\n%s\n' "$last_assistant_text"
} > "$context_path"

index_path="$out_dir/INDEX.md"
{
  if [[ ! -f "$index_path" ]]; then
    printf '# Auto-review index\n\nReviews queued by the Stop hook when an agent says "%s".\n\n' "$trigger"
    printf '| Timestamp | Reviewer | Source | LOC | Status |\n'
    printf '|-----------|----------|--------|-----|--------|\n'
  fi
  printf '| %s | %s | %s | %s | queued |\n' "$ts" "$reviewer" "$artifact_kind" "$loc_changed"
} >> "$index_path"

nohup setsid bash -c '
  cd "$1" || exit
  shift
  exec "$@"
' bash "$cwd" \
  python -m llm_client review-artifact \
    --artifact-file "$artifact_path" \
    --artifact-label "auto-review $ts ($artifact_kind, $loc_changed loc)" \
    --context-file "$context_path" \
    --reviewer "$reviewer" \
    --workspace "$cwd" \
    --timeout 2400 \
    --out "$review_path" \
  </dev/null >/dev/null 2>"$log_path" &

printf 'auto-adversarial-review queued: %s (artifact=%s loc=%s reviewer=%s)\n' \
  "$review_path" "$artifact_kind" "$loc_changed" "$reviewer" >&2

exit 0
