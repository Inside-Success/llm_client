"""Registry-first native structured-output capability resolution.

litellm's capability map lags new OpenRouter releases: deepseek-v4-flash and
minimax-m3 were marked unsupported, which silently rerouted schema-capable
models onto the instructor fallback (and crashed where instructor is not
installed — onto-canon6 extraction, 2026-07-11). The curated llm_client
registry is authoritative for models it knows; litellm remains the fallback
for unknown ids.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import yaml

from llm_client.core.models import _reset_config, supports_structured_output
from llm_client.execution.structured_runtime import _model_supports_native_schema


@pytest.fixture(autouse=True)
def _reset():
    """Reset config cache between tests."""
    _reset_config()
    yield
    _reset_config()


def _write_config(tmp_path, models):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    return str(path)


_BASE = {
    "name": "x",
    "provider": "openrouter",
    "api_key_env": "OPENROUTER_API_KEY",
    "intelligence": 40,
    "speed": 50,
    "cost": 0.1,
    "context": 128000,
}


class TestSupportsStructuredOutput:
    def test_known_model_returns_registry_value(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            [
                {**_BASE, "litellm_id": "openrouter/x/schema-yes", "structured_output": True},
                {**_BASE, "litellm_id": "openrouter/x/schema-no", "structured_output": False},
            ],
        )
        with patch.dict(os.environ, {"LLM_CLIENT_MODELS_CONFIG": cfg}):
            assert supports_structured_output("openrouter/x/schema-yes") is True
            assert supports_structured_output("openrouter/x/schema-no") is False

    def test_unknown_model_returns_none(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            [{**_BASE, "litellm_id": "openrouter/x/schema-yes", "structured_output": True}],
        )
        with patch.dict(os.environ, {"LLM_CLIENT_MODELS_CONFIG": cfg}):
            assert supports_structured_output("openrouter/x/not-registered") is None

    def test_default_registry_knows_deepseek_v4_flash(self):
        """The packaged registry declares the model litellm's map lags on."""
        assert supports_structured_output("openrouter/deepseek/deepseek-v4-flash") is True
        assert supports_structured_output("openrouter/minimax/minimax-m3") is True
        assert supports_structured_output("openrouter/openai/gpt-5.6-sol") is True
        assert supports_structured_output("openrouter/openai/gpt-5.6-luna") is True

    def test_current_direct_gpt_routes_advertise_native_schema_support(self):
        """Current direct routes retain observed native-schema capability."""
        assert supports_structured_output("gpt-5.5") is None
        assert supports_structured_output("openrouter/openai/gpt-5.5") is None
        assert supports_structured_output("gpt-5.6") is True
        assert supports_structured_output("gpt-5.6-terra") is True


class TestModelSupportsNativeSchema:
    def test_observed_direct_gpt_routes_use_registry_capability(self):
        """Known direct routes do not depend on LiteLLM's fallback capability map."""
        with patch("litellm.supports_response_schema") as litellm_map:
            assert _model_supports_native_schema("gpt-5.6") is True
            assert _model_supports_native_schema("gpt-5.6-terra") is True
            litellm_map.assert_not_called()

    def test_registry_overrides_stale_litellm_false(self, tmp_path):
        """A curated schema-capable model wins over litellm's stale 'False'."""
        cfg = _write_config(
            tmp_path,
            [{**_BASE, "litellm_id": "openrouter/x/new-model", "structured_output": True}],
        )
        with (
            patch.dict(os.environ, {"LLM_CLIENT_MODELS_CONFIG": cfg}),
            patch("litellm.supports_response_schema") as litellm_map,
        ):
            assert _model_supports_native_schema("openrouter/x/new-model") is True
            litellm_map.assert_not_called()

    def test_registry_false_blocks_native_path(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            [{**_BASE, "litellm_id": "openrouter/x/no-schema", "structured_output": False}],
        )
        with (
            patch.dict(os.environ, {"LLM_CLIENT_MODELS_CONFIG": cfg}),
            patch("litellm.supports_response_schema") as litellm_map,
        ):
            assert _model_supports_native_schema("openrouter/x/no-schema") is False
            litellm_map.assert_not_called()

    def test_unknown_model_falls_back_to_litellm(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            [{**_BASE, "litellm_id": "openrouter/x/known", "structured_output": True}],
        )
        with (
            patch.dict(os.environ, {"LLM_CLIENT_MODELS_CONFIG": cfg}),
            patch("litellm.supports_response_schema", return_value=True) as litellm_map,
        ):
            assert _model_supports_native_schema("openrouter/x/unknown") is True
            litellm_map.assert_called_once_with(model="openrouter/x/unknown")
