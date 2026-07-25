"""Agent-drivable exact route-certification queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from llm_client.route_certification import RouteCertificationStore


def cmd_query(args: argparse.Namespace) -> None:
    """Print one exact-key route view or an explicit not-found envelope."""

    view = RouteCertificationStore(Path(args.root)).query(
        resolved_model=args.resolved_model,
        upstream_provider_endpoint=(None if args.unknown_provider else args.provider),
        execution_mode=args.execution_mode,
        schema_class=args.schema_class,
        schema_sha256=args.schema_sha256,
    )
    if view is None:
        print(json.dumps({"found": False}, sort_keys=True))
        return
    print(
        json.dumps(
            {"found": True, "route": view.model_dump(mode="json")},
            indent=2,
            sort_keys=True,
        )
    )


def register_parser(subparsers: Any) -> None:
    """Register exact route-certification inspection commands."""

    parser = subparsers.add_parser(
        "route-certification",
        help="Query exact model/provider/schema route observations",
    )
    operations = parser.add_subparsers(
        dest="route_certification_operation", required=True
    )
    query = operations.add_parser(
        "query", help="Query one exact route and schema digest"
    )
    query.add_argument("--root", required=True, help="Observation store directory")
    query.add_argument("--resolved-model", required=True)
    provider = query.add_mutually_exclusive_group(required=True)
    provider.add_argument(
        "--provider", help="Exact OpenRouter provider_responses.endpoint_id"
    )
    provider.add_argument(
        "--unknown-provider",
        action="store_true",
        help="Query observations lacking upstream provider identity",
    )
    query.add_argument(
        "--execution-mode",
        required=True,
        choices=("native_json_schema", "instructor", "text"),
    )
    query.add_argument("--schema-class", required=True)
    query.add_argument("--schema-sha256", required=True)
    query.set_defaults(handler=cmd_query)
