"""Read one stored prompt as it was actually sent."""

from __future__ import annotations

import argparse
import json
from typing import Any


def _render(record: dict[str, Any], *, full: bool, min_dup_bytes: int) -> str:
    from llm_client.prompt_inspection import find_duplicated_content_in_text

    messages = record.get("messages") or []
    lines: list[str] = []
    header = (
        f"call {record['id']}  {record['timestamp']}  "
        f"{record.get('project')}  task={record.get('task')}"
    )
    lines.append(header)
    lines.append(f"model={record.get('model')}  trace_id={record.get('trace_id')}")
    if record.get("prompt_ref"):
        lines.append(f"prompt_ref={record['prompt_ref']}")
    lines.append("")

    if not messages:
        lines.append(
            "No prompt stored for this call. Content persistence may have been "
            "metadata-only, or this row predates prompt capture."
        )
        return "\n".join(lines)

    total = sum(len(str(m.get("content", "")).encode("utf-8")) for m in messages)
    lines.append(f"{'#':>2}  {'role':<10} {'bytes':>12}  share")
    lines.append("-" * 40)
    for index, message in enumerate(messages):
        size = len(str(message.get("content", "")).encode("utf-8"))
        share = size / total * 100 if total else 0.0
        lines.append(f"{index:>2}  {message.get('role')!s:<10} {size:>12,}  {share:5.1f}%")
    lines.append(f"{'':>2}  {'TOTAL':<10} {total:>12,}  100.0%")

    # A stored prompt is flat text, so the JSON has to be recovered before
    # duplication is visible at all - scanning the text finds nothing, because
    # the copies are indented differently.
    duplicates = find_duplicated_content_in_text(
        "\n".join(str(m.get("content", "")) for m in messages),
        min_bytes=min_dup_bytes,
    )
    if duplicates:
        wasted = sum(item.wasted_bytes for item in duplicates)
        lines.append("")
        lines.append(f"repeated content: {wasted:,} bytes wasted ({wasted / total * 100:.1f}% of prompt)")
        for item in duplicates:
            lines.append(f"  {item.describe()}")

    if full:
        lines.append("")
        for index, message in enumerate(messages):
            lines.append(f"----- message[{index}] role={message.get('role')} -----")
            lines.append(str(message.get("content", "")))
    return "\n".join(lines)


def _cmd_prompt_show(args: argparse.Namespace) -> None:
    from llm_client.observability.replay import get_call_record

    record = get_call_record(args.call_id)
    if args.json:
        print(json.dumps({"id": record["id"], "messages": record.get("messages")}, indent=2))
        return
    print(_render(record, full=args.full, min_dup_bytes=args.min_duplicate_bytes))


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "prompt-show",
        help="Show one stored call's assembled prompt, with size attribution",
    )
    parser.add_argument("call_id", type=int, help="llm_calls.id of the call to read")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full prompt text, not just the size breakdown",
    )
    parser.add_argument("--json", action="store_true", help="Emit the raw messages as JSON")
    parser.add_argument(
        "--min-duplicate-bytes",
        type=int,
        default=10_000,
        help="Smallest repeated block worth reporting (default 10000)",
    )
    parser.set_defaults(handler=_cmd_prompt_show)
