"""Agent-drivable CLI for provider-free inventory and explicit limit reads."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import ValidationError

from llm_client.provider_limits import (
    OpenRouterKeyEnvironmentV1,
    OpenRouterProviderLimitPreflightV1,
    ProviderLimitErrorCodeV1,
    ProviderLimitObservationErrorV1,
    ProviderLimitObserverConfigV1,
    inspect_openrouter_key_environment_v1,
    observe_openrouter_key_limit_v1,
)


def _print_error(error: ProviderLimitObservationErrorV1) -> None:
    """Write one stable JSON error envelope without external payload content."""
    print(json.dumps(error.as_dict(), sort_keys=True), file=sys.stderr)


def cmd_openrouter(args: argparse.Namespace) -> None:
    """Inspect locally or perform one explicitly authorized OpenRouter status read."""
    try:
        result: OpenRouterKeyEnvironmentV1 | OpenRouterProviderLimitPreflightV1
        if args.inspect_only:
            result = inspect_openrouter_key_environment_v1()
        else:
            try:
                config = ProviderLimitObserverConfigV1(
                    timeout_seconds=args.timeout_seconds,
                    max_response_bytes=args.max_response_bytes,
                )
            except ValidationError as exc:
                raise ProviderLimitObservationErrorV1(
                    ProviderLimitErrorCodeV1.CONFIG_INVALID,
                    "Provider-limit observer configuration is invalid.",
                ) from exc
            result = observe_openrouter_key_limit_v1(
                allow_provider_read=True,
                config=config,
            )
    except ProviderLimitObservationErrorV1 as exc:
        _print_error(exc)
        raise SystemExit(2) from exc
    print(result.model_dump_json(indent=2))


def register_parser(subparsers: Any) -> None:
    """Register the provider-limit command and OpenRouter operation."""
    parser = subparsers.add_parser(
        "provider-limit",
        help="Inspect provider credentials or read provider-reported key limits",
    )
    provider_subparsers = parser.add_subparsers(
        dest="provider_limit_provider",
        required=True,
        help="Provider implementation",
    )
    openrouter = provider_subparsers.add_parser(
        "openrouter",
        help="Inspect or observe one canonical OpenRouter key",
    )
    action = openrouter.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--inspect-only",
        action="store_true",
        help="Validate the post-import environment without provider access",
    )
    action.add_argument(
        "--allow-provider-read",
        action="store_true",
        help="Authorize exactly one authenticated GET /api/v1/key request",
    )
    openrouter.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Finite timeout for the authenticated provider read",
    )
    openrouter.add_argument(
        "--max-response-bytes",
        type=int,
        default=65_536,
        help="Maximum accepted current-key response size",
    )
    openrouter.set_defaults(handler=cmd_openrouter)
