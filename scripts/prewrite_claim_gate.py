#!/usr/bin/env python3
"""Dependency-light native hook adapter for canonical pre-write claims."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.prewrite_claim_fast import (  # noqa: E402
    DEFAULT_CLAIMS_DIR,
    DEFAULT_PROJECTION_PATH,
    DEFAULT_RECEIPT_PATH,
    FastPreWriteError,
    evaluate_prewrite_fast,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--mode", choices=("off", "observe", "enforce"))
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--projection-path", type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Compatibility alias: use <dir>/authority-projection-v1.json.",
    )
    parser.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    parser.add_argument("--json", action="store_true", help="Print the decision instead of native hook output.")
    return parser


def _git_root(cwd: str) -> Path:
    completed = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise FastPreWriteError(completed.stderr.strip() or "unable to resolve Git worktree")
    return Path(completed.stdout.strip()).resolve()


def _load_mode(repo_root: Path) -> str:
    import yaml  # type: ignore[import-untyped]

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload is None:
        return "off"
    if not isinstance(payload, dict):
        raise FastPreWriteError(f"{config_path} must contain a YAML mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise FastPreWriteError("meta-process.yaml meta_process must be a mapping")
    claims = meta_process.get("claims", {})
    if claims is None:
        return "off"
    if not isinstance(claims, dict):
        raise FastPreWriteError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise FastPreWriteError("claims.prewrite_mode must be one of: off, observe, enforce")
    return str(mode)


def _mode(payload: dict[str, Any], explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    return _load_mode(_git_root(cwd))


def _native_notice(message: str) -> str:
    return json.dumps({"systemMessage": message}, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload: object = {}
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise FastPreWriteError("PreToolUse payload must be a JSON object")
        mode = _mode(payload, args.mode)
        projection_path = args.projection_path
        if projection_path is None and args.cache_dir is not None:
            projection_path = args.cache_dir / "authority-projection-v1.json"
        if projection_path is None:
            projection_path = DEFAULT_PROJECTION_PATH
        decision = evaluate_prewrite_fast(
            payload,
            client=args.client,
            mode=mode,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            receipt_path=args.receipt_path,
        )
    except (json.JSONDecodeError, FastPreWriteError, OSError, ValueError) as exc:
        try:
            mode = _mode(payload if isinstance(payload, dict) else {}, args.mode)
        except Exception:
            mode = args.mode or "enforce"
        message = f"Pre-write claim gate could not validate this write: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "mode": mode,
                        "reason_code": "invalid_hook_payload",
                        "error": str(exc),
                    },
                    sort_keys=True,
                )
            )
        elif mode == "observe":
            print(_native_notice(f"OBSERVE ONLY: {message}"))
        elif mode == "enforce":
            print(message, file=sys.stderr)
        return 2 if mode == "enforce" else 0

    if args.json:
        print(json.dumps(decision, indent=2, sort_keys=True))
        return 0
    if decision["decision"] == "deny":
        detail = ", ".join(decision["details"])
        message = f"Pre-write claim denied ({decision['reason_code']})"
        if detail:
            message += f": {detail}"
        if decision["recovery"]:
            message += f". {decision['recovery']}"
        print(message, file=sys.stderr)
        return 2
    if decision["decision"] == "observe_violation":
        print(_native_notice(f"OBSERVE ONLY: pre-write claim violation ({decision['reason_code']})."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
