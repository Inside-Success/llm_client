"""Unit tests for pure routing/config resolution."""

from llm_client.core.config import ClientConfig
from llm_client.core.client_dispatch import _resolve_call_plan
from llm_client.core.model_availability import clear_model_unavailability, record_model_unavailability
from llm_client.core.routing import CallRequest, resolve_api_base_for_model, resolve_call


def test_resolve_call_openrouter_normalizes_and_deduplicates() -> None:
    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(
        CallRequest(
            model="gpt-5",
            fallback_models=["gpt-5", "openrouter/openai/gpt-4", "gpt-4"],
        ),
        cfg,
    )

    assert plan.primary_model == "openrouter/openai/gpt-5"
    assert plan.models == ["openrouter/openai/gpt-5", "openrouter/openai/gpt-4"]
    assert plan.fallback_models == ["openrouter/openai/gpt-4"]
    assert plan.routing_trace["routing_policy"] == "openrouter_on"
    assert plan.routing_trace["normalized_from"] == "gpt-5"
    assert plan.routing_trace["normalized_to"] == "openrouter/openai/gpt-5"


def test_resolve_call_direct_preserves_model_ids() -> None:
    cfg = ClientConfig(routing_policy="direct")
    plan = resolve_call(
        CallRequest(model="gpt-5", fallback_models=["gpt-4"]),
        cfg,
    )

    assert plan.primary_model == "gpt-5"
    assert plan.models == ["gpt-5", "gpt-4"]
    assert plan.routing_trace["routing_policy"] == "openrouter_off"
    assert "normalized_from" not in plan.routing_trace
    assert "normalization_events" not in plan.routing_trace


def test_resolve_api_base_prefers_explicit_and_injects_openrouter_default() -> None:
    cfg = ClientConfig(
        routing_policy="openrouter",
        openrouter_api_base="https://router.example/api/v1",
    )

    assert (
        resolve_api_base_for_model("openrouter/openai/gpt-4", None, cfg)
        == "https://router.example/api/v1"
    )
    assert resolve_api_base_for_model("gpt-4", None, cfg) is None
    assert (
        resolve_api_base_for_model("openrouter/openai/gpt-4", "https://override", cfg)
        == "https://override"
    )


def test_resolve_call_plan_logs_provider_governance_reroute_loudly(caplog) -> None:
    """A rule that pins a bare alias to a different provider/bill than the
    caller's literal string implied must never be silently invisible, even
    when the canonical model string is unchanged from what was requested."""
    import logging

    cfg = ClientConfig(routing_policy="openrouter")

    with caplog.at_level(logging.WARNING, logger="llm_client.core.client_dispatch"):
        plan = _resolve_call_plan(
            model="gpt-5.6-terra",
            fallback_models=None,
            api_base=None,
            config=cfg,
        )

    assert plan.primary_model == "gpt-5.6-terra"
    warning_records = [
        record for record in caplog.records if "ROUTE_PROVIDER_GOVERNANCE" in record.message
    ]
    assert len(warning_records) == 1
    assert warning_records[0].levelno == logging.WARNING
    message = warning_records[0].message
    assert "gpt-5.6-terra" in message
    assert "direct_provider" in message


def test_resolve_call_plan_skips_temporarily_unavailable_models() -> None:
    cfg = ClientConfig(routing_policy="direct")

    class ExhaustedError(Exception):
        pass

    clear_model_unavailability()
    record_model_unavailability(
        "gemini/gemini-2.5-flash",
        ExhaustedError(
            "Rate limit exceeded for GenerateContentRequestsPerDayPerProjectPerModel-FreeTier. "
            "Please try again tomorrow."
        ),
    )

    plan = _resolve_call_plan(
        model="gemini/gemini-2.5-flash",
        fallback_models=[
            "gemini/gemini-2.5-flash-lite",
            "openrouter/deepseek/deepseek-chat",
        ],
        api_base=None,
        config=cfg,
    )
    clear_model_unavailability()

    assert plan.primary_model == "gemini/gemini-2.5-flash-lite"
    assert plan.models == [
        "gemini/gemini-2.5-flash-lite",
        "openrouter/deepseek/deepseek-chat",
    ]
    suppressed = plan.routing_trace["suppressed_models"]
    assert suppressed[0]["model"] == "gemini/gemini-2.5-flash"
    assert suppressed[0]["reason"] == "provider_daily_quota_exhausted"


def test_record_model_unavailability_uses_provider_retry_hint_for_daily_quota() -> None:
    class ExhaustedError(Exception):
        pass

    clear_model_unavailability()
    record = record_model_unavailability(
        "gemini/gemini-2.5-flash",
        ExhaustedError(
            "Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day. "
            '{"details":[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"34820s"}]}'
        ),
        now_monotonic=0.0,
    )
    clear_model_unavailability()

    assert record is not None
    assert record["reason"] == "provider_daily_quota_exhausted"
    assert record["cooldown_s"] == 34820.0


def test_resolve_call_gpt54_preserves_banned_identity_under_openrouter_policy() -> None:
    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="gpt-5.4"), cfg)

    assert plan.primary_model == "gpt-5.4"
    assert plan.models == ["gpt-5.4"]
    assert "normalized_from" not in plan.routing_trace


def test_resolve_call_gpt56_preserves_certified_direct_route_under_openrouter_policy() -> None:
    """A route certified through Responses API must not be silently proxied."""

    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="gpt-5.6"), cfg)

    assert plan.primary_model == "gpt-5.6"
    assert plan.models == ["gpt-5.6"]
    assert plan.routing_trace["routing_policy"] == "openrouter_on"
    assert "normalized_from" not in plan.routing_trace
    assert plan.routing_trace["provider_governance_events"] == [
        {
            "event": "model_canonicalized",
            "reason": (
                "GPT-5.6 Sol's certified strict-schema route is OpenAI Responses API, "
                "not the default OpenRouter proxy."
            ),
            "route_class": "direct_provider",
            "canonical_model": "gpt-5.6",
            "from": "gpt-5.6",
            "to": "gpt-5.6",
        }
    ]


def test_resolve_call_gpt56_terra_preserves_certified_direct_route_under_openrouter_policy() -> None:
    """Terra has the same direct native-schema routing requirement as Sol."""

    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="gpt-5.6-terra"), cfg)

    assert plan.primary_model == "gpt-5.6-terra"
    assert plan.models == ["gpt-5.6-terra"]
    # The exact-alias rule pins this bare alias to direct OpenAI billing even
    # though the canonical string is identical to what the caller passed in.
    # That must still surface as a governance event so the reroute is never
    # silently invisible (see llm_client/core/client_dispatch.py's
    # ROUTE_PROVIDER_GOVERNANCE warning log).
    assert plan.routing_trace["provider_governance_events"] == [
        {
            "event": "model_canonicalized",
            "reason": (
                "GPT-5.6 Terra's certified strict-schema route is OpenAI Responses API, "
                "not the default OpenRouter proxy."
            ),
            "route_class": "direct_provider",
            "canonical_model": "gpt-5.6-terra",
            "from": "gpt-5.6-terra",
            "to": "gpt-5.6-terra",
        }
    ]


def test_resolve_call_gpt54_preserves_banned_identity_under_direct_policy() -> None:
    cfg = ClientConfig(routing_policy="direct")
    plan = resolve_call(CallRequest(model="gpt-5.4"), cfg)

    assert plan.primary_model == "gpt-5.4"
    assert plan.models == ["gpt-5.4"]
    assert plan.routing_trace["routing_policy"] == "openrouter_off"


def test_resolve_call_prefixed_gpt54_preserves_banned_identity() -> None:
    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="openrouter/openai/gpt-5.4"), cfg)

    assert plan.primary_model == "openrouter/openai/gpt-5.4"
    assert plan.models == ["openrouter/openai/gpt-5.4"]
    assert "normalized_from" not in plan.routing_trace


def test_resolve_call_normalizes_google_gemini_alias_to_openrouter() -> None:
    """OpenRouter policy should canonicalize google/gemini provider aliases."""
    cfg = ClientConfig(routing_policy="openrouter")

    plan = resolve_call(
        CallRequest(model="google/gemini-2.0-flash-001"),
        cfg,
    )

    assert plan.primary_model == "openrouter/google/gemini-2.0-flash-001"
    assert plan.routing_trace["normalized_from"] == "google/gemini-2.0-flash-001"
    assert plan.routing_trace["normalized_to"] == "openrouter/google/gemini-2.0-flash-001"


def test_resolve_call_normalizes_minimax_m3_alias_to_openrouter_default() -> None:
    """MiniMax-M3 aliases should canonicalize to the shared default route."""
    cfg = ClientConfig(routing_policy="openrouter")

    plan = resolve_call(CallRequest(model="MiniMax-M3"), cfg)

    assert plan.primary_model == "openrouter/minimax/minimax-m3"
    assert plan.routing_trace["normalized_from"] == "MiniMax-M3"
    assert plan.routing_trace["normalized_to"] == "openrouter/minimax/minimax-m3"
    assert plan.routing_trace["provider_governance_events"] == [
        {
            "event": "model_canonicalized",
            "reason": "Bare MiniMax-M3 aliases use the shared OpenRouter default route.",
            "route_class": "openrouter",
            "canonical_model": "openrouter/minimax/minimax-m3",
            "from": "MiniMax-M3",
            "to": "openrouter/minimax/minimax-m3",
        }
    ]


def test_resolve_call_normalizes_direct_minimax_m3_alias_to_openrouter_default() -> None:
    """Direct MiniMax-M3 aliases should use the shared OpenRouter default."""
    cfg = ClientConfig(routing_policy="openrouter")

    plan = resolve_call(CallRequest(model="minimax/MiniMax-M3"), cfg)

    assert plan.primary_model == "openrouter/minimax/minimax-m3"
    assert plan.routing_trace["normalized_from"] == "minimax/MiniMax-M3"
    assert plan.routing_trace["normalized_to"] == "openrouter/minimax/minimax-m3"


def test_resolve_call_normalizes_bare_gemini_model_id() -> None:
    """Bare Gemini ids should canonicalize before provider routing kicks in."""
    cfg = ClientConfig(routing_policy="openrouter")

    plan = resolve_call(
        CallRequest(model="gemini-2.5-flash"),
        cfg,
    )

    assert plan.primary_model == "gemini/gemini-2.5-flash"
    assert plan.routing_trace["normalized_from"] == "gemini-2.5-flash"
    assert plan.routing_trace["normalized_to"] == "gemini/gemini-2.5-flash"
    assert plan.routing_trace["provider_governance_events"] == [
        {
            "event": "model_canonicalized",
            "reason": "Bare Gemini ids are not stable provider identities and must be canonicalized.",
            "route_class": "direct_provider",
            "canonical_model": "gemini/gemini-2.5-flash",
            "from": "gemini-2.5-flash",
            "to": "gemini/gemini-2.5-flash",
        }
    ]


def test_resolve_call_direct_still_canonicalizes_bare_gemini_model_id() -> None:
    """Direct policy still needs a canonical provider id for bare Gemini models."""
    cfg = ClientConfig(routing_policy="direct")

    plan = resolve_call(
        CallRequest(model="gemini-3-flash-preview"),
        cfg,
    )

    assert plan.primary_model == "gemini/gemini-3-flash-preview"
    assert plan.models == ["gemini/gemini-3-flash-preview"]
    assert plan.routing_trace["routing_policy"] == "openrouter_off"
    assert plan.routing_trace["normalized_from"] == "gemini-3-flash-preview"
    assert plan.routing_trace["normalized_to"] == "gemini/gemini-3-flash-preview"
