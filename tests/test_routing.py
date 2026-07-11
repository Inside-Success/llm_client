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
        fallback_models=["gemini/gemini-2.5-flash-lite", "openrouter/openai/gpt-5.4-mini"],
        api_base=None,
        config=cfg,
    )
    clear_model_unavailability()

    assert plan.primary_model == "gemini/gemini-2.5-flash-lite"
    assert plan.models == ["gemini/gemini-2.5-flash-lite", "openrouter/openai/gpt-5.4-mini"]
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


def test_resolve_call_gpt54_canonicalizes_to_codex_under_openrouter_policy() -> None:
    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="gpt-5.4"), cfg)

    assert plan.primary_model == "codex/gpt-5.4"
    assert plan.models == ["codex/gpt-5.4"]
    assert plan.routing_trace["normalized_from"] == "gpt-5.4"
    assert plan.routing_trace["normalized_to"] == "codex/gpt-5.4"
    assert plan.routing_trace["provider_governance_events"] == [
        {
            "event": "model_canonicalized",
            "reason": "Exact gpt-5.4 aliases must use the Codex SDK lane.",
            "route_class": "agent_sdk",
            "canonical_model": "codex/gpt-5.4",
            "from": "gpt-5.4",
            "to": "codex/gpt-5.4",
        }
    ]


def test_resolve_call_gpt54_canonicalizes_to_codex_under_direct_policy() -> None:
    cfg = ClientConfig(routing_policy="direct")
    plan = resolve_call(CallRequest(model="gpt-5.4"), cfg)

    assert plan.primary_model == "codex/gpt-5.4"
    assert plan.models == ["codex/gpt-5.4"]
    assert plan.routing_trace["routing_policy"] == "openrouter_off"


def test_resolve_call_prefixed_gpt54_canonicalizes_to_codex() -> None:
    cfg = ClientConfig(routing_policy="openrouter")
    plan = resolve_call(CallRequest(model="openrouter/openai/gpt-5.4"), cfg)

    assert plan.primary_model == "codex/gpt-5.4"
    assert plan.models == ["codex/gpt-5.4"]
    assert plan.routing_trace["normalized_from"] == "openrouter/openai/gpt-5.4"
    assert plan.routing_trace["normalized_to"] == "codex/gpt-5.4"


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
