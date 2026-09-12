"""Tests for Langfuse callback integration.

Verifies that Langfuse callbacks activate only when configured via env vars
and the langfuse package is available. Tests metadata injection into litellm
kwargs for callback propagation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import patch

import litellm
import pytest

from llm_client.langfuse_callbacks import (
    _is_active,
    configure_langfuse_callbacks,
    inject_metadata,
)


@pytest.fixture(autouse=True)
def _reset_langfuse_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset module state and litellm callbacks between tests."""
    import llm_client.langfuse_callbacks as mod

    monkeypatch.delenv("LITELLM_CALLBACKS", raising=False)
    monkeypatch.delenv("LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_OTEL_HOST", raising=False)
    original_message_logging = litellm.turn_off_message_logging
    mod._initialized = False
    mod._configured_callback = None
    mod._configured_content_policy = None
    for callback in ("langfuse_otel", "langfuse"):
        while callback in litellm.success_callback:
            litellm.success_callback.remove(callback)
        while callback in litellm.failure_callback:
            litellm.failure_callback.remove(callback)
    yield
    litellm.turn_off_message_logging = original_message_logging


class TestConfigureLangfuseCallbacks:
    """Tests for configure_langfuse_callbacks()."""

    def test_no_env_var_does_nothing(self) -> None:
        """When LITELLM_CALLBACKS is not set, no callbacks are registered."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LITELLM_CALLBACKS", None)
            result = configure_langfuse_callbacks()
        assert result.enabled is False
        assert result.content_policy is None
        assert "langfuse" not in litellm.success_callback
        assert "langfuse" not in litellm.failure_callback

    def test_env_var_without_langfuse_does_nothing(self) -> None:
        """When LITELLM_CALLBACKS is set but doesn't include langfuse, skip."""
        with patch.dict(os.environ, {"LITELLM_CALLBACKS": "prometheus,datadog"}):
            result = configure_langfuse_callbacks()
        assert result.enabled is False
        assert "langfuse" not in litellm.success_callback

    def test_env_var_with_langfuse_but_not_installed(self) -> None:
        """When langfuse is requested but not importable, warn and skip."""
        with (
            patch.dict(os.environ, {"LITELLM_CALLBACKS": "langfuse"}),
            patch.dict("sys.modules", {"langfuse": None}),
            patch("builtins.__import__", side_effect=ImportError("no langfuse")),
        ):
            # mock-ok: testing behavior when optional dependency is missing
            result = configure_langfuse_callbacks()
        assert result.enabled is False
        assert "langfuse" not in litellm.success_callback

    def test_env_var_with_langfuse_installed_activates(self) -> None:
        """Langfuse defaults to metadata-only external telemetry."""
        # mock-ok: simulating langfuse availability without installing it
        import types

        fake_langfuse = types.ModuleType("langfuse")
        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_CALLBACKS": "langfuse",
                    "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT": "metadata_only",
                },
            ),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            result = configure_langfuse_callbacks()
        assert result.enabled is True
        assert result.callback == "langfuse"
        assert result.content_policy == "metadata_only"
        assert litellm.turn_off_message_logging is True
        assert "langfuse" in litellm.success_callback
        assert "langfuse" in litellm.failure_callback

    def test_idempotent(self) -> None:
        """Calling configure twice doesn't double-register callbacks."""
        import types

        fake_langfuse = types.ModuleType("langfuse")
        with (
            patch.dict(os.environ, {"LITELLM_CALLBACKS": "langfuse"}),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            configure_langfuse_callbacks()
            configure_langfuse_callbacks()
        assert litellm.success_callback.count("langfuse") == 1
        assert litellm.failure_callback.count("langfuse") == 1

    def test_comma_separated_env(self) -> None:
        """LITELLM_CALLBACKS with multiple values, including langfuse."""
        import types

        fake_langfuse = types.ModuleType("langfuse")
        with (
            patch.dict(
                os.environ, {"LITELLM_CALLBACKS": "prometheus, langfuse, datadog"}
            ),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            result = configure_langfuse_callbacks()
        assert result.enabled is True
        assert "langfuse" in litellm.success_callback

    def test_otel_callback_uses_otel_host_and_metadata_only_default(self) -> None:
        """The current OTEL callback name uses its endpoint and redacts content."""
        import types

        fake_langfuse = types.ModuleType("langfuse")
        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_CALLBACKS": "langfuse_otel",
                    "LANGFUSE_OTEL_HOST": "https://otel.example.test",
                    "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT": "metadata_only",
                },
            ),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            result = configure_langfuse_callbacks()
        assert result.enabled is True
        assert result.callback == "langfuse_otel"
        assert result.host == "https://otel.example.test"
        assert result.content_policy == "metadata_only"
        assert litellm.turn_off_message_logging is True
        assert "langfuse_otel" in litellm.success_callback

    def test_full_content_requires_explicit_policy(self) -> None:
        """Full-content export is possible only through an explicit setting."""
        import types

        fake_langfuse = types.ModuleType("langfuse")
        litellm.turn_off_message_logging = False
        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_CALLBACKS": "langfuse_otel",
                    "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT": "full",
                },
            ),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            result = configure_langfuse_callbacks()
        assert result.content_policy == "full"
        assert litellm.turn_off_message_logging is False

    def test_full_content_does_not_weaken_an_existing_process_policy(self) -> None:
        """A callback cannot re-enable content another component disabled."""
        import types

        fake_langfuse = types.ModuleType("langfuse")
        litellm.turn_off_message_logging = True
        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_CALLBACKS": "langfuse_otel",
                    "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT": "full",
                },
            ),
            patch.dict("sys.modules", {"langfuse": fake_langfuse}),
        ):
            result = configure_langfuse_callbacks()
        assert result.content_policy == "full"
        assert litellm.turn_off_message_logging is True

    def test_invalid_content_policy_fails_before_callback_registration(self) -> None:
        """Unknown content policies fail loudly instead of leaking by fallback."""
        with (
            patch.dict(
                os.environ,
                {
                    "LITELLM_CALLBACKS": "langfuse_otel",
                    "LLM_CLIENT_EXTERNAL_OBSERVABILITY_CONTENT": "everything",
                },
            ),
            pytest.raises(ValueError, match="must be 'metadata_only' or 'full'"),
        ):
            configure_langfuse_callbacks()
        assert "langfuse_otel" not in litellm.success_callback
        import llm_client.langfuse_callbacks as mod

        assert mod._initialized is False


class TestIsActive:
    """Tests for _is_active()."""

    def test_inactive_by_default(self) -> None:
        """Without configuration, Langfuse is not active."""
        assert _is_active() is False

    def test_active_after_configuration(self) -> None:
        """After successful configuration, reports active."""
        litellm.success_callback.append("langfuse")
        assert _is_active() is True

    def test_active_with_otel_callback(self) -> None:
        """The current OTEL callback is recognized as active."""
        litellm.success_callback.append("langfuse_otel")
        assert _is_active() is True


class TestInjectMetadata:
    """Tests for inject_metadata()."""

    def test_injects_task_and_trace_id(self) -> None:
        """Both task and trace_id are added to metadata dict."""
        kwargs: dict[str, object] = {}
        inject_metadata(kwargs, task="my_task", trace_id="trace-123")
        meta = kwargs["metadata"]
        assert isinstance(meta, dict)
        assert meta["task"] == "my_task"
        assert meta["trace_id"] == "trace-123"
        assert meta["_llm_client_logged"] is True

    def test_noop_when_both_none(self) -> None:
        """When both values are None, marker is still injected."""
        kwargs: dict[str, object] = {}
        inject_metadata(kwargs, task=None, trace_id=None)
        meta = kwargs["metadata"]
        assert isinstance(meta, dict)
        assert meta["_llm_client_logged"] is True

    def test_partial_injection(self) -> None:
        """Only non-None values are injected, marker always present."""
        kwargs: dict[str, object] = {}
        inject_metadata(kwargs, task="only_task", trace_id=None)
        meta = kwargs["metadata"]
        assert isinstance(meta, dict)
        assert meta["task"] == "only_task"
        assert meta["_llm_client_logged"] is True

    def test_preserves_existing_metadata(self) -> None:
        """Existing metadata keys are preserved, new ones merged."""
        kwargs: dict[str, object] = {"metadata": {"existing_key": "value"}}
        inject_metadata(kwargs, task="my_task", trace_id="trace-456")
        meta = kwargs["metadata"]
        assert isinstance(meta, dict)
        assert meta["existing_key"] == "value"
        assert meta["task"] == "my_task"
        assert meta["trace_id"] == "trace-456"

    def test_overrides_conflicting_metadata(self) -> None:
        """If metadata already has task/trace_id, our values win."""
        kwargs: dict[str, object] = {"metadata": {"task": "old_task"}}
        inject_metadata(kwargs, task="new_task", trace_id=None)
        meta = kwargs["metadata"]
        assert isinstance(meta, dict)
        assert meta["task"] == "new_task"
