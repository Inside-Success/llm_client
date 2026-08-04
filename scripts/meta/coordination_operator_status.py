#!/usr/bin/env python3
"""Show one message's human-identifiable recipient and truthful response state."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    raise RuntimeError("Unable to locate repo root containing enforced_planning/")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import client_session_metadata, coordination_claims, coordination_messages  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument(
        "--codex-session-index",
        type=Path,
        default=client_session_metadata.DEFAULT_CODEX_SESSION_INDEX,
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    claims_dir = (args.claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    store = coordination_messages.CoordinationMessageStore(
        root=args.root or coordination_messages.default_message_root(claims_dir),
        claims_dir=claims_dir,
    )
    status = store.status(
        coordination_messages.MessageStatusRequest(message_id=args.message_id)
    )
    readout = client_session_metadata.build_coordination_response_readout(
        status,
        claims=coordination_claims.list_claims(
            claims_dir=claims_dir,
            include_inactive=True,
        ),
        codex_session_index=args.codex_session_index,
    )
    if args.json:
        print(readout.model_dump_json(indent=2))
        return 0

    display = readout.client_display.display_name or (
        f"<{readout.client_display.state}>"
    )
    print(f"Message: {readout.message_id}")
    print(f"Recipient thread: {display}")
    print(f"Recipient session: {readout.recipient_session_id}")
    print(
        "Internal session name(s): "
        + (", ".join(readout.internal_session_names) or "<none>")
    )
    print(
        "Active claim scope(s): "
        + (", ".join(readout.active_claim_scopes) or "<none>")
    )
    if readout.retained_claim_scopes:
        print(
            "Retained inactive claim scope(s): "
            + ", ".join(readout.retained_claim_scopes)
        )
    print(f"Message state: {readout.message_state}")
    print(f"Response state: {readout.response_state}")
    print("Completion: not evaluated")
    if readout.acknowledgement_disposition:
        print(f"Acknowledgement: {readout.acknowledgement_disposition}")
    if readout.acknowledgement_note:
        print(f"Recipient note: {readout.acknowledgement_note}")
    if readout.response_ref:
        print(f"Response ref: {readout.response_ref}")
    if readout.manual_resume_command:
        print("Manual resume (not automatic wake):")
        print(readout.manual_resume_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
