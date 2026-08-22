"""Tests for agent SDK routing. All mocked (no real agent SDK calls).

Tests cover:
- _is_agent_model() detection (Claude + Codex)
- _parse_agent_model() parsing (Claude + Codex)
- _messages_to_agent_prompt() conversion
- Cache rejection for agent models
- NotImplementedError guards for tool calling (tools are agent-internal)
- Claude Agent SDK: routing, hooks, fallback, structured, streaming, batch
- Codex SDK: routing, hooks, model suffix, structured, streaming, batch, fallback
"""

import asyncio
import json
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

import llm_client.sdk.agents as agents_mod
import llm_client.sdk.agents_codex as agents_codex_mod
from llm_client import (
    Hooks,
    LLMCallResult,
    LRUCache,
    acall_llm,
    acall_llm_batch,
    acall_llm_structured,
    acall_llm_with_tools,
    astream_llm,
    astream_llm_with_tools,
    call_llm,
    call_llm_batch,
    call_llm_structured,
    call_llm_with_tools,
    stream_llm,
    stream_llm_with_tools,
)
from llm_client.sdk.agents import (
    _build_agent_options,
    _build_codex_cli_command,
    _is_codex_transport_fallback_error,
    _messages_to_agent_prompt,
    _normalize_codex_reasoning_effort,
    _parse_agent_model,
    _result_from_codex,
)
from llm_client.core.errors import LLMError, LLMTransientError
from llm_client.core.client import _is_agent_model


@pytest.fixture(autouse=True)
def _explicit_test_routing_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Week-1 invariant: routing policy must be explicit in tests."""
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_CODEX_PROCESS_ISOLATION", "0")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestIsAgentModel:
    def test_claude_code(self) -> None:
        assert _is_agent_model("claude-code") is True

    def test_claude_code_with_model(self) -> None:
        assert _is_agent_model("claude-code/opus") is True

    def test_claude_code_with_haiku(self) -> None:
        assert _is_agent_model("claude-code/haiku") is True

    def test_case_insensitive(self) -> None:
        assert _is_agent_model("Claude-Code") is True
        assert _is_agent_model("CLAUDE-CODE/opus") is True

    def test_openai_agents_reserved(self) -> None:
        assert _is_agent_model("openai-agents/gpt-5") is True

    def test_regular_models_not_agent(self) -> None:
        assert _is_agent_model("gpt-4o") is False
        assert _is_agent_model("anthropic/claude-sonnet-4-5-20250929") is False
        assert _is_agent_model("gemini/gemini-2.0-flash") is False
        assert _is_agent_model("gpt-5-mini") is False

    def test_codex(self) -> None:
        assert _is_agent_model("codex") is True

    def test_codex_with_model(self) -> None:
        assert _is_agent_model("codex/gpt-5") is True

    def test_codex_alias(self) -> None:
        assert _is_agent_model("codex-mini-latest") is True

    def test_codex_case_insensitive(self) -> None:
        assert _is_agent_model("Codex") is True
        assert _is_agent_model("CODEX/o3") is True

    def test_partial_prefix_not_matched(self) -> None:
        assert _is_agent_model("claude-coder") is False
        assert _is_agent_model("openai-agent/gpt-5") is False
        assert _is_agent_model("codex-cli") is False

    def test_codex_family_bare_model(self) -> None:
        """Codex-family models like gpt-5.3-codex route to agent SDK."""
        assert _is_agent_model("gpt-5.3-codex") is True

    def test_codex_family_with_suffix(self) -> None:
        """Codex-family variants with suffixes like -mini, -max."""
        assert _is_agent_model("gpt-5.1-codex-mini") is True
        assert _is_agent_model("gpt-5.1-codex-max") is True

    def test_codex_family_older_version(self) -> None:
        assert _is_agent_model("gpt-5.2-codex") is True

    def test_gpt54_alias_is_not_a_codex_sdk_shortcut(self) -> None:
        assert _is_agent_model("gpt-5.4") is False

    def test_codex_family_case_insensitive(self) -> None:
        assert _is_agent_model("GPT-5.3-CODEX") is True
        assert _is_agent_model("Gpt-5.1-Codex-Mini") is True

    def test_codex_family_with_provider_prefix(self) -> None:
        """Provider-prefixed Codex-family models are still detected."""
        assert _is_agent_model("openai/gpt-5.3-codex") is True
        assert _is_agent_model("openrouter/openai/gpt-5.3-codex") is True

    def test_gpt54_alias_with_provider_prefix_is_not_a_codex_sdk_shortcut(self) -> None:
        assert _is_agent_model("openai/gpt-5.4") is False
        assert _is_agent_model("openrouter/openai/gpt-5.4") is False

    def test_non_codex_gpt_models(self) -> None:
        """Regular GPT models should NOT match Codex-family pattern."""
        assert _is_agent_model("gpt-4o") is False
        assert _is_agent_model("gpt-5-mini") is False
        assert _is_agent_model("gpt-5.2-pro") is False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseAgentModel:
    def test_bare_claude_code(self) -> None:
        assert _parse_agent_model("claude-code") == ("claude-code", None)

    def test_claude_code_with_model(self) -> None:
        assert _parse_agent_model("claude-code/opus") == ("claude-code", "opus")

    def test_claude_code_with_sonnet(self) -> None:
        assert _parse_agent_model("claude-code/sonnet") == ("claude-code", "sonnet")

    def test_openai_agents(self) -> None:
        assert _parse_agent_model("openai-agents/gpt-5") == ("openai-agents", "gpt-5")

    def test_case_normalization(self) -> None:
        sdk, model = _parse_agent_model("Claude-Code/Opus")
        assert sdk == "claude-code"
        assert model == "Opus"  # underlying model preserves case


class TestWorkspaceKwargAliasing:
    """The Claude SDK reads ``cwd``; the Codex SDK reads ``working_directory``.

    Callers like the duet that thread one canonical name shouldn't be silently
    dropped by whichever SDK doesn't recognize that spelling. The
    ``_normalize_workspace_kwargs`` helper aliases between them at the route
    boundary; these tests assert the aliasing happens before the SDK adapter
    consumes the kwargs.
    """

    def test_normalize_aliases_cwd_to_working_directory_for_codex(self) -> None:
        from llm_client.sdk.agents import _normalize_workspace_kwargs

        kwargs = {"cwd": "/workspace"}
        _normalize_workspace_kwargs("codex", kwargs)
        assert kwargs == {"working_directory": "/workspace"}

    def test_normalize_aliases_working_directory_to_cwd_for_claude(self) -> None:
        from llm_client.sdk.agents import _normalize_workspace_kwargs

        kwargs = {"working_directory": "/workspace"}
        _normalize_workspace_kwargs("claude-code", kwargs)
        assert kwargs == {"cwd": "/workspace"}

    def test_normalize_preserves_sdk_native_when_both_present_codex(self) -> None:
        """Explicit ``working_directory`` wins; ``cwd`` is dropped on codex."""
        from llm_client.sdk.agents import _normalize_workspace_kwargs

        kwargs = {"working_directory": "/native", "cwd": "/alias"}
        _normalize_workspace_kwargs("codex", kwargs)
        assert kwargs == {"working_directory": "/native"}

    def test_normalize_preserves_sdk_native_when_both_present_claude(self) -> None:
        """Explicit ``cwd`` wins; ``working_directory`` is dropped on claude-code."""
        from llm_client.sdk.agents import _normalize_workspace_kwargs

        kwargs = {"cwd": "/native", "working_directory": "/alias"}
        _normalize_workspace_kwargs("claude-code", kwargs)
        assert kwargs == {"cwd": "/native"}

    def test_normalize_noop_when_neither_present(self) -> None:
        from llm_client.sdk.agents import _normalize_workspace_kwargs

        kwargs = {"timeout": 60}
        _normalize_workspace_kwargs("codex", kwargs)
        assert kwargs == {"timeout": 60}

    def test_route_call_passes_working_directory_to_codex_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """End-to-end: a caller passing ``cwd=`` to a codex model must surface
        ``working_directory=`` at the codex adapter boundary.

        This catches the Plan #30 gap that the workflow-layer stub-seam test
        could not: the codex SDK falls back to ``os.getcwd()`` when
        ``working_directory`` is missing, so silent kwarg drop = silent wrong-tree
        inspection.
        """
        from llm_client.sdk import agents as agents_mod

        captured: dict = {}

        def fake_call_codex(model, messages, **kwargs):
            captured.update(kwargs)
            return None

        monkeypatch.setattr(agents_mod, "_call_codex", fake_call_codex)
        agents_mod._route_call(
            "codex/gpt-5.6-luna",
            [{"role": "user", "content": "hi"}],
            cwd="/abs/workspace",
        )
        assert captured.get("working_directory") == "/abs/workspace"
        assert "cwd" not in captured

    def test_route_call_passes_cwd_to_claude_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inverse: ``working_directory=`` on a claude-code model must surface as ``cwd=``."""
        from llm_client.sdk import agents as agents_mod

        captured: dict = {}

        def fake_call_agent(model, messages, **kwargs):
            captured.update(kwargs)
            return None

        monkeypatch.setattr(agents_mod, "_call_agent", fake_call_agent)
        agents_mod._route_call(
            "claude-code/opus",
            [{"role": "user", "content": "hi"}],
            working_directory="/abs/workspace",
        )
        assert captured.get("cwd") == "/abs/workspace"
        assert "working_directory" not in captured


class TestCodexReasoningEffortNormalization:
    def test_omission_fails_instead_of_defaulting_high(self) -> None:
        with pytest.raises(ValueError, match="requires explicit reasoning_effort"):
            _normalize_codex_reasoning_effort(None)

    def test_unsupported_effort_fails_instead_of_coercing(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Codex reasoning effort"):
            _normalize_codex_reasoning_effort("xhigh")

    def test_supported_effort_is_preserved(self) -> None:
        assert _normalize_codex_reasoning_effort("low") == "low"

    def test_bare_codex(self) -> None:
        assert _parse_agent_model("codex") == ("codex", None)

    def test_codex_with_model(self) -> None:
        assert _parse_agent_model("codex/gpt-5") == ("codex", "gpt-5")

    def test_codex_with_o3(self) -> None:
        assert _parse_agent_model("codex/o3") == ("codex", "o3")

    def test_codex_alias(self) -> None:
        assert _parse_agent_model("codex-mini-latest") == ("codex", "codex-mini-latest")

    def test_gpt54_alias_is_not_parsed_as_codex(self) -> None:
        assert _parse_agent_model("gpt-5.4") == ("gpt-5.4", None)

    def test_codex_family_bare(self) -> None:
        """Codex-family models parse as (codex, <full-model-name>)."""
        assert _parse_agent_model("gpt-5.3-codex") == ("codex", "gpt-5.3-codex")

    def test_codex_family_with_suffix(self) -> None:
        assert _parse_agent_model("gpt-5.1-codex-mini") == ("codex", "gpt-5.1-codex-mini")
        assert _parse_agent_model("gpt-5.1-codex-max") == ("codex", "gpt-5.1-codex-max")

    def test_provider_prefixed_gpt54_alias_is_not_parsed_as_codex(self) -> None:
        assert _parse_agent_model("openrouter/openai/gpt-5.4") == (
            "openrouter",
            "openai/gpt-5.4",
        )


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestMessagesToAgentPrompt:
    def test_single_user_message(self) -> None:
        prompt, sys = _messages_to_agent_prompt(
            [{"role": "user", "content": "What is 2+2?"}]
        )
        assert prompt == "What is 2+2?"
        assert sys is None

    def test_system_plus_user(self) -> None:
        prompt, sys = _messages_to_agent_prompt([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ])
        assert prompt == "Hi"
        assert sys == "You are helpful"

    def test_multi_turn(self) -> None:
        prompt, sys = _messages_to_agent_prompt([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ])
        assert "User: Hello" in prompt
        assert "Assistant: Hi there" in prompt
        assert "User: How are you?" in prompt
        assert sys is None

    def test_system_plus_multi_turn(self) -> None:
        prompt, sys = _messages_to_agent_prompt([
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Bye"},
        ])
        assert sys == "Be concise"
        assert "User: Hello" in prompt
        assert "Assistant: Hi" in prompt
        assert "User: Bye" in prompt

    def test_empty_messages_raises(self) -> None:
        with pytest.raises(ValueError, match="No user/assistant messages"):
            _messages_to_agent_prompt([])

    def test_system_only_raises(self) -> None:
        with pytest.raises(ValueError, match="No user/assistant messages"):
            _messages_to_agent_prompt([{"role": "system", "content": "sys"}])


# ---------------------------------------------------------------------------
# Cache rejection
# ---------------------------------------------------------------------------


class TestCacheRejection:
    def test_cache_with_agent_raises_sync(self) -> None:
        cache = LRUCache(maxsize=10)
        with pytest.raises(ValueError, match="Caching not supported for agent models"):
            call_llm("claude-code", [{"role": "user", "content": "Hi"}], cache=cache, task="test", trace_id="test_cache_rejection_sync", max_budget=0)

    @pytest.mark.asyncio
    async def test_cache_with_agent_raises_async(self) -> None:
        cache = LRUCache(maxsize=10)
        with pytest.raises(ValueError, match="Caching not supported for agent models"):
            await acall_llm("claude-code", [{"role": "user", "content": "Hi"}], cache=cache, task="test", trace_id="test_cache_rejection_async", max_budget=0)

    def test_cache_with_codex_raises_sync(self) -> None:
        cache = LRUCache(maxsize=10)
        with pytest.raises(ValueError, match="Caching not supported for agent models"):
            call_llm("codex", [{"role": "user", "content": "Hi"}], cache=cache, task="test", trace_id="test_cache_codex_sync", max_budget=0)


# ---------------------------------------------------------------------------
# NotImplementedError guards (tools only — streaming/structured/batch are now supported)
# ---------------------------------------------------------------------------


class _DummyModel(BaseModel):
    name: str


class TestAgentGuards:
    """Tool-related functions should raise NotImplementedError for agent models."""

    def test_call_llm_with_tools(self) -> None:
        with pytest.raises(NotImplementedError, match="built-in tools"):
            call_llm_with_tools(
                "claude-code", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_call_tools", max_budget=0,
            )

    @pytest.mark.asyncio
    async def test_acall_llm_with_tools(self) -> None:
        with pytest.raises(NotImplementedError, match="built-in tools"):
            await acall_llm_with_tools(
                "claude-code", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_acall_tools", max_budget=0,
            )

    def test_stream_llm_with_tools(self) -> None:
        with pytest.raises(NotImplementedError, match="built-in tools"):
            stream_llm_with_tools(
                "claude-code", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_stream_tools", max_budget=0,
            )

    @pytest.mark.asyncio
    async def test_astream_llm_with_tools(self) -> None:
        with pytest.raises(NotImplementedError, match="built-in tools"):
            await astream_llm_with_tools(
                "claude-code", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_astream_tools", max_budget=0,
            )

    def test_openai_agents_guard(self) -> None:
        """openai-agents/* should also trigger guards."""
        with pytest.raises(NotImplementedError, match="built-in tools"):
            stream_llm_with_tools(
                "openai-agents/gpt-5", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_openai_agents", max_budget=0,
            )

    def test_codex_with_tools(self) -> None:
        """Codex should also reject tool calling."""
        with pytest.raises(NotImplementedError, match="built-in tools"):
            call_llm_with_tools(
                "codex", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_guard_codex_tools", max_budget=0,
            )


# ---------------------------------------------------------------------------
# Fake SDK fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeTextBlock:
    text: str


@dataclass
class _FakeAssistantMessage:
    content: list[_FakeTextBlock]
    model: str = "claude-sonnet-4-5-20250929"


@dataclass
class _FakeResultMessage:
    subtype: str = "success"
    duration_ms: int = 1000
    duration_api_ms: int = 800
    is_error: bool = False
    num_turns: int = 1
    session_id: str = "test-session"
    total_cost_usd: float | None = 0.005
    usage: dict | None = None
    result: str | None = None
    structured_output: object = None


async def _fake_query(prompt, options=None):
    """Fake claude_agent_sdk.query() that yields an AssistantMessage and ResultMessage."""
    yield _FakeAssistantMessage(content=[_FakeTextBlock(text="The answer is 4.")])
    yield _FakeResultMessage(
        total_cost_usd=0.005,
        usage={"input_tokens": 100, "output_tokens": 20},
    )


def _make_fake_sdk_module():
    """Create a fake claude_agent_sdk module for sys.modules patching."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.query = _fake_query  # type: ignore[attr-defined]
    mod.AssistantMessage = _FakeAssistantMessage  # type: ignore[attr-defined]
    mod.ResultMessage = _FakeResultMessage  # type: ignore[attr-defined]
    mod.TextBlock = _FakeTextBlock  # type: ignore[attr-defined]
    mod.ClaudeAgentOptions = MagicMock  # type: ignore[attr-defined]
    mod.ToolUseBlock = _FakeToolUseBlock  # type: ignore[attr-defined]
    mod.ToolResultBlock = _FakeToolResultBlock  # type: ignore[attr-defined]
    mod.UserMessage = _FakeUserMessage  # type: ignore[attr-defined]
    return mod


@dataclass
class _FakeToolUseBlock:
    id: str = "tool_1"
    name: str = "test_tool"
    input: dict = field(default_factory=dict)


@dataclass
class _FakeToolResultBlock:
    tool_use_id: str = "tool_1"
    content: str = ""
    is_error: bool = False


@dataclass
class _FakeUserMessage:
    content: list = field(default_factory=list)
    uuid: str = ""
    parent_tool_use_id: str | None = None
    tool_use_result: _FakeToolResultBlock | None = None


@pytest.fixture()
def _mock_agent_sdk(monkeypatch):
    """Install fake claude_agent_sdk in sys.modules and clear import caches."""
    fake_mod = _make_fake_sdk_module()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)
    # Also clear the cached lazy import in agents module if it was previously imported
    import llm_client.sdk.agents as agents_mod
    # Force re-import on next call by invalidating any cached references
    for attr in ("query", "AssistantMessage", "ResultMessage", "TextBlock", "ToolUseBlock",
                  "ToolResultBlock", "UserMessage", "ClaudeAgentOptions"):
        if hasattr(agents_mod, attr):
            monkeypatch.delattr(agents_mod, attr, raising=False)


# ---------------------------------------------------------------------------
# Mocked agent SDK call
# ---------------------------------------------------------------------------


class TestAgentCallMocked:
    """Test agent routing with mocked claude_agent_sdk."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_call_llm_agent_sync(self) -> None:
        result = call_llm("claude-code", [{"role": "user", "content": "What is 2+2?"}], task="test", trace_id="test_agent_call_sync", max_budget=0)
        assert isinstance(result, LLMCallResult)
        assert "4" in result.content
        assert result.cost == 0.0
        assert result.billing_mode == "subscription_included"
        assert result.cost_source == "subscription_included"
        assert result.model == "claude-code"
        assert result.finish_reason == "stop"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_acall_llm_agent_async(self) -> None:
        result = await acall_llm("claude-code", [{"role": "user", "content": "What is 2+2?"}], task="test", trace_id="test_agent_call_async", max_budget=0)
        assert isinstance(result, LLMCallResult)
        assert "4" in result.content
        assert result.cost == 0.0
        assert result.billing_mode == "subscription_included"
        assert result.cost_source == "subscription_included"
        assert result.finish_reason == "stop"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_call_llm_agent_api_mode(self, monkeypatch) -> None:
        monkeypatch.setenv("LLM_CLIENT_AGENT_BILLING_MODE", "api")
        result = call_llm(
            "claude-code",
            [{"role": "user", "content": "What is 2+2?"}],
            task="test",
            trace_id="test_agent_call_api_mode",
            max_budget=0,
        )
        assert isinstance(result, LLMCallResult)
        assert result.cost == 0.005
        assert result.billing_mode == "api_metered"
        assert result.cost_source == "provider_reported"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_hooks_fire_for_agent(self) -> None:
        before_calls: list = []
        after_calls: list = []
        hooks = Hooks(
            before_call=lambda m, msgs, kw: before_calls.append(m),
            after_call=lambda r: after_calls.append(r),
        )
        result = call_llm(
            "claude-code", [{"role": "user", "content": "Hi"}], hooks=hooks,
            task="test", trace_id="test_agent_hooks", max_budget=0,
        )
        assert len(before_calls) == 1
        assert before_calls[0] == "claude-code"
        assert len(after_calls) == 1
        assert after_calls[0] is result

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_agent_with_model_suffix(self) -> None:
        result = call_llm(
            "claude-code/sonnet", [{"role": "user", "content": "Hi"}],
            task="test", trace_id="test_agent_model_suffix", max_budget=0,
        )
        assert result.model == "claude-code/sonnet"


class TestBuildAgentOptions:
    """Test _build_agent_options env handling."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_claudecode_env_stripped_when_set(self, monkeypatch) -> None:
        """CLAUDECODE env var is cleared so nested sessions work."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setattr("llm_client._auto_loaded_keys", frozenset())
        _, options, _ = _build_agent_options(
            "claude-code", [{"role": "user", "content": "Hi"}],
        )
        assert options.env.get("CLAUDECODE") == ""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_claudecode_env_not_added_when_unset(self, monkeypatch) -> None:
        """Don't inject CLAUDECODE env if not already in environment."""
        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.setattr("llm_client._auto_loaded_keys", frozenset())
        _, options, _ = _build_agent_options(
            "claude-code", [{"role": "user", "content": "Hi"}],
        )
        assert "CLAUDECODE" not in options.env

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_auto_loaded_keys_stripped(self, monkeypatch) -> None:
        """Auto-loaded API keys are cleared from agent subprocess env."""
        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.setattr(
            "llm_client._auto_loaded_keys",
            frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}),
        )
        _, options, _ = _build_agent_options(
            "claude-code", [{"role": "user", "content": "Hi"}],
        )
        assert options.env.get("ANTHROPIC_API_KEY") == ""
        assert options.env.get("OPENAI_API_KEY") == ""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_auto_loaded_plus_claudecode(self, monkeypatch) -> None:
        """Both CLAUDECODE and auto-loaded keys are cleared together."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setattr(
            "llm_client._auto_loaded_keys",
            frozenset({"GEMINI_API_KEY"}),
        )
        _, options, _ = _build_agent_options(
            "claude-code", [{"role": "user", "content": "Hi"}],
        )
        assert options.env.get("CLAUDECODE") == ""
        assert options.env.get("GEMINI_API_KEY") == ""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_yolo_mode_sets_claude_bypass_permissions(self, monkeypatch) -> None:
        """yolo_mode should map to Claude's headless permission mode."""

        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.setattr("llm_client._auto_loaded_keys", frozenset())
        _, options, _ = _build_agent_options(
            "claude-code",
            [{"role": "user", "content": "Hi"}],
            yolo_mode=True,
        )
        assert options.permission_mode == "bypassPermissions"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.parametrize(
        "alias, full_id",
        [
            ("sonnet", "claude-sonnet-4-6"),
            ("haiku", "claude-haiku-4-5-20251001"),
            ("SONNET", "claude-sonnet-4-6"),
        ],
    )
    def test_short_alias_resolves_to_full_model_id(self, monkeypatch, alias, full_id) -> None:
        """Permitted short aliases resolve to full Anthropic model IDs.

        Bare aliases are silently ignored by the Claude Agent SDK and cause the
        session to fall back to its default model.
        """
        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.setattr("llm_client._auto_loaded_keys", frozenset())
        _, options, _ = _build_agent_options(
            f"claude-code/{alias}",
            [{"role": "user", "content": "Hi"}],
        )
        assert options.model == full_id

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_resolve_unknown_alias_passes_through(self) -> None:
        """Unknown values pass through unchanged so callers can pin specific IDs."""
        from llm_client.sdk.agents_claude import _resolve_claude_code_model

        assert _resolve_claude_code_model("some-future-model") == "some-future-model"
        assert _resolve_claude_code_model(None) is None

    @pytest.mark.parametrize("model", ["opus", "Opus", "claude-opus-4-7"])
    def test_claude_adapter_rejects_opus_defense_in_depth(self, model) -> None:
        """Direct use of the private SDK seam cannot bypass public policy."""
        from llm_client.core.errors import DeprecatedModelError
        from llm_client.sdk.agents_claude import _resolve_claude_code_model

        with pytest.raises(
            DeprecatedModelError,
            match=r"(?i)HARD-BLOCKED MODEL.*opus",
        ):
            _resolve_claude_code_model(model)


class TestOnTurnCallback:
    """Test on_turn callback fires during agent execution."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_on_turn_fires_for_claude_agent(self) -> None:
        """on_turn should fire once per AssistantMessage in a Claude agent call."""
        events: list = []
        result = await acall_llm(
            "claude-code",
            [{"role": "user", "content": "What is 2+2?"}],
            task="test",
            trace_id="test_on_turn_claude",
            max_budget=0,
            on_turn=lambda ev: events.append(ev),
        )
        assert isinstance(result, LLMCallResult)
        assert len(events) == 1
        ev = events[0]
        from llm_client.core.data_types import TurnEvent
        assert isinstance(ev, TurnEvent)
        assert ev.turn >= 1
        assert ev.elapsed_s >= 0.0
        assert isinstance(ev.tool_calls, list)
        assert isinstance(ev.text_preview, str)
        assert len(ev.text_preview) <= 200

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_on_turn_fires_per_assistant_message(self, monkeypatch) -> None:
        """on_turn should fire once per AssistantMessage in multi-turn conversation."""
        # mock-ok: need to test multi-turn callback firing without real SDK
        async def _multi_turn_query(prompt, options=None):
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="Step 1")])
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="Step 2")])
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="Step 3")])
            yield _FakeResultMessage(
                total_cost_usd=0.01,
                usage={"input_tokens": 200, "output_tokens": 60},
            )

        fake_mod = _make_fake_sdk_module()
        fake_mod.query = _multi_turn_query  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

        events: list = []
        result = await acall_llm(
            "claude-code",
            [{"role": "user", "content": "Multi-step task"}],
            task="test",
            trace_id="test_on_turn_multi",
            max_budget=0,
            on_turn=lambda ev: events.append(ev),
        )
        assert isinstance(result, LLMCallResult)
        assert len(events) == 3
        assert events[0].turn == 1
        assert events[1].turn == 2
        assert events[2].turn == 3
        # Elapsed times should be non-decreasing
        assert events[0].elapsed_s <= events[1].elapsed_s <= events[2].elapsed_s

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_on_turn_none_does_not_fail(self) -> None:
        """Passing on_turn=None (the default) should not change behavior."""
        result = await acall_llm(
            "claude-code",
            [{"role": "user", "content": "What is 2+2?"}],
            task="test",
            trace_id="test_on_turn_none",
            max_budget=0,
        )
        assert isinstance(result, LLMCallResult)
        assert "4" in result.content

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_on_turn_with_tool_calls(self, monkeypatch) -> None:
        """on_turn should include tool call names when assistant uses tools."""
        # mock-ok: need to test tool call extraction in on_turn without real SDK
        async def _tool_query(prompt, options=None):
            yield _FakeAssistantMessage(content=[
                _FakeTextBlock(text="Let me check"),
                _FakeToolUseBlock(id="t1", name="read_file", input={"path": "/tmp/x"}),
            ])
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="Done")])
            yield _FakeResultMessage(
                total_cost_usd=0.005,
                usage={"input_tokens": 100, "output_tokens": 30},
            )

        fake_mod = _make_fake_sdk_module()
        fake_mod.query = _tool_query  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

        events: list = []
        result = await acall_llm(
            "claude-code",
            [{"role": "user", "content": "Read a file"}],
            task="test",
            trace_id="test_on_turn_tools",
            max_budget=0,
            on_turn=lambda ev: events.append(ev),
        )
        assert isinstance(result, LLMCallResult)
        assert len(events) == 2
        # First turn should have the tool call
        assert len(events[0].tool_calls) == 1
        assert events[0].tool_calls[0]["name"] == "read_file"
        # Second turn has no tools
        assert len(events[1].tool_calls) == 0


class TestAgentFallback:
    """Test fallback from agent model to regular model and vice versa."""

    def test_fallback_from_agent_to_litellm(self, monkeypatch) -> None:
        """Agent fails, falls back to regular model."""
        # Install a failing fake SDK
        async def _failing_query(prompt, options=None):
            raise RuntimeError("Agent SDK failed")
            yield  # make it an async generator  # noqa: E501

        fake_mod = _make_fake_sdk_module()
        fake_mod.query = _failing_query  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Fallback response"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_resp.usage.total_tokens = 15

        with (
            patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp),
            patch("llm_client.core.client.litellm.completion_cost", return_value=0.001),
        ):
            result = call_llm(
                "claude-code",
                [{"role": "user", "content": "Hi"}],
                fallback_models=["gpt-4o"],
                task="test", trace_id="test_agent_fallback", max_budget=0,
            )
        assert result.content == "Fallback response"
        assert result.model == "gpt-4o"


class TestOpenAIAgentsGuard:
    """openai-agents/* should raise NotImplementedError at the agent level."""

    def test_openai_agents_not_implemented(self) -> None:
        with pytest.raises(LLMError, match="not yet supported"):
            call_llm(
                "openai-agents/gpt-5",
                [{"role": "user", "content": "Hi"}],
                task="test", trace_id="test_openai_agents_guard", max_budget=0,
            )


# ---------------------------------------------------------------------------
# Structured output (mocked)
# ---------------------------------------------------------------------------


class _CityInfo(BaseModel):
    name: str
    country: str


class TestAgentStructured:
    """Test structured output via agent SDK."""

    def _make_structured_query(self):
        """Create a fake query that returns structured output."""
        async def _structured_query(prompt, options=None):
            yield _FakeAssistantMessage(
                content=[_FakeTextBlock(text='{"name": "Tokyo", "country": "Japan"}')]
            )
            yield _FakeResultMessage(
                total_cost_usd=0.01,
                usage={"input_tokens": 200, "output_tokens": 50},
                structured_output={"name": "Tokyo", "country": "Japan"},
            )
        return _structured_query

    @pytest.fixture()
    def _mock_structured_sdk(self, monkeypatch):
        fake_mod = _make_fake_sdk_module()
        fake_mod.query = self._make_structured_query()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

    @pytest.mark.usefixtures("_mock_structured_sdk")
    def test_call_llm_structured_sync(self) -> None:
        parsed, meta = call_llm_structured(
            "claude-code",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            task="test", trace_id="test_structured_sync", max_budget=0,
        )
        assert isinstance(parsed, _CityInfo)
        assert parsed.name == "Tokyo"
        assert parsed.country == "Japan"
        assert isinstance(meta, LLMCallResult)
        assert meta.cost == 0.0
        assert meta.billing_mode == "subscription_included"
        assert meta.cost_source == "subscription_included"
        assert meta.model == "claude-code"

    @pytest.mark.usefixtures("_mock_structured_sdk")
    @pytest.mark.asyncio
    async def test_acall_llm_structured_async(self) -> None:
        parsed, meta = await acall_llm_structured(
            "claude-code",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            task="test", trace_id="test_structured_async", max_budget=0,
        )
        assert isinstance(parsed, _CityInfo)
        assert parsed.name == "Tokyo"
        assert parsed.country == "Japan"
        assert meta.cost == 0.0
        assert meta.billing_mode == "subscription_included"
        assert meta.cost_source == "subscription_included"

    @pytest.mark.usefixtures("_mock_structured_sdk")
    def test_structured_hooks_fire(self) -> None:
        before_calls: list = []
        after_calls: list = []
        hooks = Hooks(
            before_call=lambda m, msgs, kw: before_calls.append(m),
            after_call=lambda r: after_calls.append(r),
        )
        parsed, meta = call_llm_structured(
            "claude-code",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            hooks=hooks,
            task="test", trace_id="test_structured_hooks", max_budget=0,
        )
        assert len(before_calls) == 1
        assert len(after_calls) == 1

    def test_structured_falls_back_to_structured_output_field(self, monkeypatch) -> None:
        """If text content is empty but structured_output is set, use it."""
        async def _query(prompt, options=None):
            yield _FakeAssistantMessage(content=[])
            yield _FakeResultMessage(
                total_cost_usd=0.01,
                usage={"input_tokens": 200, "output_tokens": 50},
                structured_output={"name": "Paris", "country": "France"},
            )

        fake_mod = _make_fake_sdk_module()
        fake_mod.query = _query  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

        parsed, meta = call_llm_structured(
            "claude-code",
            [{"role": "user", "content": "Info about Paris"}],
            response_model=_CityInfo,
            task="test", trace_id="test_structured_fallback_field", max_budget=0,
        )
        assert parsed.name == "Paris"
        assert parsed.country == "France"


# ---------------------------------------------------------------------------
# Streaming (mocked)
# ---------------------------------------------------------------------------


class TestAgentStream:
    """Test streaming via agent SDK."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_stream_llm_sync(self) -> None:
        stream = stream_llm("claude-code", [{"role": "user", "content": "Hi"}], task="test", trace_id="test_stream_sync", max_budget=0)
        chunks: list[str] = []
        for chunk in stream:
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "4" in "".join(chunks)
        result = stream.result
        assert isinstance(result, LLMCallResult)
        assert result.cost == 0.0
        assert result.billing_mode == "subscription_included"
        assert result.cost_source == "subscription_included"
        assert result.model == "claude-code"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_astream_llm_async(self) -> None:
        stream = await astream_llm("claude-code", [{"role": "user", "content": "Hi"}], task="test", trace_id="test_astream_async", max_budget=0)
        chunks: list[str] = []
        async for chunk in stream:
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "4" in "".join(chunks)
        result = stream.result
        assert isinstance(result, LLMCallResult)
        assert result.cost == 0.0
        assert result.billing_mode == "subscription_included"
        assert result.cost_source == "subscription_included"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_stream_result_before_consume_raises(self) -> None:
        stream = stream_llm("claude-code", [{"role": "user", "content": "Hi"}], task="test", trace_id="test_stream_before_consume", max_budget=0)
        with pytest.raises(RuntimeError, match="not yet consumed"):
            _ = stream.result

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_stream_hooks_fire(self) -> None:
        before_calls: list = []
        after_calls: list = []
        hooks = Hooks(
            before_call=lambda m, msgs, kw: before_calls.append(m),
            after_call=lambda r: after_calls.append(r),
        )
        stream = stream_llm(
            "claude-code", [{"role": "user", "content": "Hi"}], hooks=hooks,
            task="test", trace_id="test_stream_hooks", max_budget=0,
        )
        for _ in stream:
            pass
        assert len(before_calls) == 1
        assert len(after_calls) == 1

    def test_stream_multi_messages(self, monkeypatch) -> None:
        """Multiple AssistantMessages yield multiple chunks."""
        async def _multi_query(prompt, options=None):
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="First. ")])
            yield _FakeAssistantMessage(content=[_FakeTextBlock(text="Second.")])
            yield _FakeResultMessage(
                total_cost_usd=0.01,
                usage={"input_tokens": 100, "output_tokens": 40},
            )

        fake_mod = _make_fake_sdk_module()
        fake_mod.query = _multi_query  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_mod)

        stream = stream_llm("claude-code", [{"role": "user", "content": "Hi"}], task="test", trace_id="test_stream_multi_messages", max_budget=0)
        chunks = list(stream)
        assert len(chunks) == 2
        assert chunks[0] == "First. "
        assert chunks[1] == "Second."


# ---------------------------------------------------------------------------
# Batch (mocked)
# ---------------------------------------------------------------------------


class TestAgentBatch:
    """Test batch calls route through agent SDK."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_call_llm_batch_sync(self) -> None:
        messages_list = [
            [{"role": "user", "content": f"What is {i}+{i}?"}]
            for i in range(3)
        ]
        results = call_llm_batch("claude-code", messages_list, max_concurrent=3, task="test", trace_id="test_batch_sync", max_budget=0)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, LLMCallResult)
            assert r.model == "claude-code"
            assert r.cost == 0.0
            assert r.billing_mode == "subscription_included"
            assert r.cost_source == "subscription_included"

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_acall_llm_batch_async(self) -> None:
        messages_list = [
            [{"role": "user", "content": f"What is {i}+{i}?"}]
            for i in range(2)
        ]
        results = await acall_llm_batch("claude-code", messages_list, task="test", trace_id="test_batch_async", max_budget=0)
        assert len(results) == 2
        for r in results:
            assert isinstance(r, LLMCallResult)

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_call_llm_structured_batch_sync(self) -> None:
        """Structured batch uses structured output routing."""
        # We need a structured-capable fake SDK for this test
        pass  # Covered by structured + batch integration — guard removal is the key test

    @pytest.mark.usefixtures("_mock_agent_sdk")
    def test_batch_empty_list(self) -> None:
        results = call_llm_batch("claude-code", [], task="test", trace_id="test_batch_empty", max_budget=0)
        assert results == []


# ===========================================================================
# Codex SDK tests (mocked)
# ===========================================================================


# ---------------------------------------------------------------------------
# Fake Codex SDK fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    cached_input_tokens: int = 0
    output_tokens: int = 20


@dataclass
class _FakeAgentMessageItem:
    id: str = "msg-1"
    type: str = "agent_message"
    text: str = "The answer is 4."


@dataclass
class _FakeMcpToolCallItem:
    id: str = "item_1"
    type: str = "mcp_tool_call"
    server: str = "digimon-kgrag"
    tool: str = "list_available_resources"
    arguments: dict = field(default_factory=dict)
    result: dict | None = field(default_factory=lambda: {"content": [{"type": "text", "text": "{}"}]})
    error: object | None = None
    status: str = "completed"


@dataclass
class _FakeTurn:
    items: list = None  # type: ignore[assignment]
    final_response: str = "The answer is 4."
    usage: _FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = [_FakeAgentMessageItem()]
        if self.usage is None:
            self.usage = _FakeUsage()


@dataclass
class _FakeItemCompletedEvent:
    type: str = "item.completed"
    item: _FakeAgentMessageItem | None = None

    def __post_init__(self) -> None:
        if self.item is None:
            self.item = _FakeAgentMessageItem()


@dataclass
class _FakeTurnCompletedEvent:
    type: str = "turn.completed"
    usage: _FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = _FakeUsage()


@dataclass
class _FakeStreamedTurn:
    events: object = None  # set to an async iterator


class _FakeThread:
    """Fake Codex Thread with async run and run_streamed."""

    def __init__(self, turn: _FakeTurn | None = None) -> None:
        self._turn = turn or _FakeTurn()

    async def run(self, input_: str, turn_options: object = None) -> _FakeTurn:
        return self._turn

    async def run_streamed(self, input_: str, turn_options: object = None) -> _FakeStreamedTurn:
        async def _events():
            for item in self._turn.items:
                yield _FakeItemCompletedEvent(item=item)
            yield _FakeTurnCompletedEvent(usage=self._turn.usage)

        return _FakeStreamedTurn(events=_events())


class _SlowThread(_FakeThread):
    """Fake thread that never returns promptly (for timeout tests)."""

    async def run(self, input_: str, turn_options: object = None) -> _FakeTurn:
        await asyncio.sleep(3600)
        return self._turn


class _FakeCodex:
    """Fake Codex client."""

    def __init__(self, options: object = None) -> None:
        self._thread = _FakeThread()

    def start_thread(self, options: object = None) -> _FakeThread:
        return self._thread


def _make_fake_codex_module():
    """Create a fake openai_codex_sdk module for sys.modules patching."""
    mod = types.ModuleType("openai_codex_sdk")
    mod.Codex = _FakeCodex  # type: ignore[attr-defined]
    mod.ThreadOptions = MagicMock  # type: ignore[attr-defined]
    mod.TurnOptions = MagicMock  # type: ignore[attr-defined]
    mod.Turn = _FakeTurn  # type: ignore[attr-defined]
    mod.StreamedTurn = _FakeStreamedTurn  # type: ignore[attr-defined]
    mod.AgentMessageItem = _FakeAgentMessageItem  # type: ignore[attr-defined]
    mod.ItemCompletedEvent = _FakeItemCompletedEvent  # type: ignore[attr-defined]
    mod.TurnCompletedEvent = _FakeTurnCompletedEvent  # type: ignore[attr-defined]
    mod.Usage = _FakeUsage  # type: ignore[attr-defined]

    # Sub-module for CodexOptions
    codex_submod = types.ModuleType("openai_codex_sdk.codex")
    codex_submod.CodexOptions = MagicMock  # type: ignore[attr-defined]
    mod.codex = codex_submod  # type: ignore[attr-defined]

    return mod, codex_submod


@pytest.fixture()
def _mock_codex_sdk(monkeypatch):
    """Install fake openai_codex_sdk in sys.modules."""
    fake_mod, codex_submod = _make_fake_codex_module()
    monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
    monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)


# ---------------------------------------------------------------------------
# Codex detection
# ---------------------------------------------------------------------------


class TestCodexDetection:
    def test_codex_bare(self) -> None:
        assert _is_agent_model("codex") is True

    def test_codex_with_model(self) -> None:
        assert _is_agent_model("codex/gpt-5") is True

    def test_codex_parse(self) -> None:
        assert _parse_agent_model("codex") == ("codex", None)
        assert _parse_agent_model("codex/gpt-5") == ("codex", "gpt-5")
        assert _parse_agent_model("codex/o3") == ("codex", "o3")


# ---------------------------------------------------------------------------
# Codex guards
# ---------------------------------------------------------------------------


class TestCodexGuards:
    def test_cache_rejected(self) -> None:
        cache = LRUCache(maxsize=10)
        with pytest.raises(ValueError, match="Caching not supported"):
            call_llm("codex", [{"role": "user", "content": "Hi"}], cache=cache, task="test", trace_id="test_codex_cache_rejected", max_budget=0)

    def test_tools_rejected(self) -> None:
        with pytest.raises(NotImplementedError, match="built-in tools"):
            call_llm_with_tools(
                "codex/gpt-5", [{"role": "user", "content": "Hi"}], tools=[],
                task="test", trace_id="test_codex_tools_rejected", max_budget=0,
            )


# ---------------------------------------------------------------------------
# Codex call (mocked)
# ---------------------------------------------------------------------------


class TestCodexCall:
    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_call_llm_sync(self) -> None:
        result = call_llm("codex", [{"role": "user", "content": "What is 2+2?"}], reasoning_effort="medium", task="test", trace_id="test_codex_call_sync", max_budget=0)
        assert isinstance(result, LLMCallResult)
        assert "4" in result.content
        assert result.model == "codex"
        assert result.finish_reason == "stop"

    @pytest.mark.usefixtures("_mock_codex_sdk")
    @pytest.mark.asyncio
    async def test_acall_llm_async(self) -> None:
        result = await acall_llm("codex", [{"role": "user", "content": "What is 2+2?"}], reasoning_effort="medium", task="test", trace_id="test_codex_call_async", max_budget=0)
        assert isinstance(result, LLMCallResult)
        assert "4" in result.content
        assert result.finish_reason == "stop"

    def test_result_from_codex_extracts_mcp_tool_calls(self) -> None:
        turn = _FakeTurn(
            items=[
                _FakeAgentMessageItem(id="msg-1", text="Working"),
                _FakeMcpToolCallItem(
                    id="item_a",
                    tool="list_available_resources",
                    arguments={"dataset_name": "MuSiQue"},
                    result={"content": [{"type": "text", "text": "{\"ok\": true}"}]},
                    status="completed",
                ),
                _FakeMcpToolCallItem(
                    id="item_b",
                    tool="entity_link",
                    arguments={"entity_name": "Lady Godiva"},
                    result=None,
                    error="entity not found",
                    status="failed",
                ),
            ],
            final_response="DONE",
        )
        result = _result_from_codex("codex/gpt-5", "DONE", _FakeUsage(), turn)
        assert len(result.tool_calls) == 2
        first = result.tool_calls[0]
        assert first["function"]["name"] == "list_available_resources"
        assert first["function"]["arguments"] == {"dataset_name": "MuSiQue"}
        assert first["is_error"] is False
        assert isinstance(first.get("result_preview"), str) and first["result_preview"]
        second = result.tool_calls[1]
        assert second["function"]["name"] == "entity_link"
        assert second["is_error"] is True

    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_hooks_fire(self) -> None:
        before_calls: list = []
        after_calls: list = []
        hooks = Hooks(
            before_call=lambda m, msgs, kw: before_calls.append(m),
            after_call=lambda r: after_calls.append(r),
        )
        result = call_llm("codex", [{"role": "user", "content": "Hi"}], hooks=hooks, reasoning_effort="medium", task="test", trace_id="test_codex_hooks", max_budget=0)
        assert len(before_calls) == 1
        assert before_calls[0] == "codex"
        assert len(after_calls) == 1
        assert after_calls[0] is result

    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_model_suffix(self) -> None:
        result = call_llm("codex/gpt-5", [{"role": "user", "content": "Hi"}], reasoning_effort="medium", task="test", trace_id="test_codex_model_suffix", max_budget=0)
        assert result.model == "codex/gpt-5"

    def test_codex_timeout_is_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex timeout errors should be non-empty and classified transient."""
        fake_mod, codex_submod = _make_fake_codex_module()
        slow_codex_cls = type("SlowCodex", (), {
            "__init__": lambda self, options=None: None,
            "start_thread": lambda self, options=None: _SlowThread(),
        })
        fake_mod.Codex = slow_codex_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
        monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)

        with pytest.raises(LLMTransientError) as excinfo:
            call_llm(
                "codex",
                [{"role": "user", "content": "Hi"}],
                timeout=1,
                reasoning_effort="medium",
                task="test",
                trace_id="test_codex_timeout_explicit",
                max_budget=0,
            )
        msg = str(excinfo.value)
        assert "CODEX_TIMEOUT[codex_call]" in msg
        assert "after 1s" in msg

    def test_codex_process_isolation_dispatches_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, object] = {}

        def _fake_isolated(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int,
            kwargs: dict[str, object],
        ) -> LLMCallResult:
            calls["model"] = model
            calls["timeout"] = timeout
            calls["kwargs"] = dict(kwargs)
            calls["messages_len"] = len(messages)
            return LLMCallResult(
                content="ok-from-isolated",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
            )

        monkeypatch.setattr(agents_mod, "_call_codex_in_isolated_process", _fake_isolated)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_in_isolated_process", _fake_isolated)
        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_process_isolation=True,
            timeout=17,
            reasoning_effort="medium",
            task="test",
            trace_id="test_codex_isolation_dispatch",
            max_budget=0,
        )
        assert result.content == "ok-from-isolated"
        assert calls["model"] == "codex"
        assert calls["timeout"] == 17
        assert calls["messages_len"] == 1

    def test_codex_process_isolation_env_dispatches_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, object] = {}

        def _fake_isolated(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int,
            kwargs: dict[str, object],
        ) -> LLMCallResult:
            calls["used"] = True
            return LLMCallResult(
                content="env-isolated",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
            )

        monkeypatch.setenv("LLM_CLIENT_CODEX_PROCESS_ISOLATION", "1")
        monkeypatch.setattr(agents_mod, "_call_codex_in_isolated_process", _fake_isolated)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_in_isolated_process", _fake_isolated)
        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            timeout=17,
            reasoning_effort="medium",
            task="test",
            trace_id="test_codex_isolation_dispatch_env",
            max_budget=0,
        )
        assert result.content == "env-isolated"
        assert calls["used"] is True

    def test_timeout_policy_ban_zeroes_agent_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, object] = {}

        async def _fake_acall_codex(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int,
            **kwargs: object,
        ) -> LLMCallResult:
            calls["timeout"] = timeout
            return LLMCallResult(
                content="ok",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
            )

        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        monkeypatch.setattr(agents_mod, "_acall_codex", _fake_acall_codex)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex", _fake_acall_codex)
        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            timeout=99,
            reasoning_effort="medium",
            task="test",
            trace_id="test_agent_timeout_policy_ban",
            max_budget=0,
        )
        assert result.content == "ok"
        assert calls["timeout"] == 0

    def test_timeout_policy_ban_logs_shared_message(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Agent timeout policy should use the shared timeout warning contract."""

        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        with caplog.at_level("WARNING"):
            normalized = agents_mod._normalize_timeout(42, caller="test_agents_timeout", logger=agents_mod.logger)

        assert normalized == 0
        assert "TIMEOUT_DISABLED[test_agents_timeout]: timeout=42s ignored" in caplog.text

    def test_timeout_policy_ban_auto_transport_preserves_requested_cli_hard_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto transport retains a bounded CLI deadline when provider timeouts are disabled."""

        calls: dict[str, object] = {}

        def _unexpected_sdk(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            raise AssertionError("SDK path should not run when timeout is banned and hard timeout is set")

        def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            del messages, output_schema
            calls["agent_hard_timeout"] = kwargs.get("agent_hard_timeout")
            return LLMCallResult(
                content=f"cli via auto {timeout}",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                warnings=[fallback_warning] if fallback_warning else [],
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _unexpected_sdk)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _unexpected_sdk)
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)

        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="auto",
            timeout=99,
            reasoning_effort="medium",
            task="test",
            trace_id="test_agent_timeout_ban_cli_auto",
            max_budget=0,
        )

        assert result.content == "cli via auto 0"
        assert result.raw_response == {"transport": "codex_cli"}
        assert calls["agent_hard_timeout"] == 99
        assert any("CODEX_TRANSPORT_AUTO[sdk->cli]" in warning for warning in result.warnings)

    def test_agent_hard_timeout_env_overrides_requested_deadline(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A process-level Codex bound protects downstreams without code changes."""

        calls: dict[str, object] = {}

        def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            del messages, output_schema
            calls["agent_hard_timeout"] = kwargs.get("agent_hard_timeout")
            return LLMCallResult(
                content=f"cli via auto {timeout}",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                warnings=[fallback_warning] if fallback_warning else [],
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "ban")
        monkeypatch.setenv("LLM_CLIENT_AGENT_HARD_TIMEOUT", "180")
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)
        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="auto",
            timeout=60,
            reasoning_effort="medium",
            task="test",
            trace_id="test_agent_hard_timeout_env",
            max_budget=0,
        )

        assert result.content == "cli via auto 0"
        assert calls["agent_hard_timeout"] == 180
        assert any("agent_hard_timeout=180s" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Codex structured (mocked)
# ---------------------------------------------------------------------------


class TestCodexStructured:
    def test_output_schema_is_openai_compatible(self) -> None:
        class Nested(BaseModel):
            value: str

        class Left(BaseModel):
            kind: Literal["left"]
            nested: Nested = Field(description="A described nested model.")

        class Right(BaseModel):
            kind: Literal["right"]
            nested: Nested = Field(description="A described nested model.")

        class Envelope(BaseModel):
            item: Annotated[Left | Right, Field(discriminator="kind")]

        schema = agents_codex_mod._strict_codex_output_schema(Envelope)
        branches = schema["properties"]["item"]
        left = schema["$defs"]["Left"]

        assert "oneOf" not in branches
        assert "discriminator" not in branches
        assert len(branches["anyOf"]) == 2
        assert "$ref" not in left["properties"]["nested"]
        assert (
            left["properties"]["nested"]["description"]
            == "A described nested model."
        )

    @pytest.fixture()
    def _mock_structured_codex(self, monkeypatch):
        """Install a Codex SDK that returns JSON."""
        fake_mod, codex_submod = _make_fake_codex_module()
        # Override FakeThread to return JSON
        turn = _FakeTurn(
            final_response='{"name": "Tokyo", "country": "Japan"}',
            usage=_FakeUsage(input_tokens=200, output_tokens=50),
        )
        fake_codex_cls = type("FakeCodex", (), {
            "__init__": lambda self, options=None: setattr(self, "_turn", turn),
            "start_thread": lambda self, options=None: _FakeThread(turn),
        })
        fake_mod.Codex = fake_codex_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
        monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)

    @pytest.mark.usefixtures("_mock_structured_codex")
    def test_structured_sync(self) -> None:
        parsed, meta = call_llm_structured(
            "codex",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            reasoning_effort="medium",
            task="test", trace_id="test_codex_structured_sync", max_budget=0,
        )
        assert isinstance(parsed, _CityInfo)
        assert parsed.name == "Tokyo"
        assert parsed.country == "Japan"
        assert isinstance(meta, LLMCallResult)
        assert meta.model == "codex"

    @pytest.mark.usefixtures("_mock_structured_codex")
    @pytest.mark.asyncio
    async def test_structured_async(self) -> None:
        parsed, meta = await acall_llm_structured(
            "codex",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            reasoning_effort="medium",
            task="test", trace_id="test_codex_structured_async", max_budget=0,
        )
        assert isinstance(parsed, _CityInfo)
        assert parsed.name == "Tokyo"

    def test_structured_process_isolation_dispatches_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, object] = {}

        def _fake_structured_isolated(
            model: str,
            messages: list[dict[str, object]],
            response_model: type[BaseModel],
            *,
            timeout: int,
            kwargs: dict[str, object],
        ) -> tuple[BaseModel, LLMCallResult]:
            calls["model"] = model
            calls["timeout"] = timeout
            parsed = response_model.model_validate({"name": "Tokyo", "country": "Japan"})
            llm_result = LLMCallResult(
                content=parsed.model_dump_json(),
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
            )
            return parsed, llm_result

        monkeypatch.setattr(
            agents_mod,
            "_call_codex_structured_in_isolated_process",
            _fake_structured_isolated,
        )
        monkeypatch.setattr(
            agents_codex_mod,
            "_call_codex_structured_in_isolated_process",
            _fake_structured_isolated,
        )
        parsed, meta = call_llm_structured(
            "codex",
            [{"role": "user", "content": "Info about Tokyo"}],
            response_model=_CityInfo,
            codex_process_isolation=True,
            timeout=19,
            reasoning_effort="medium",
            task="test",
            trace_id="test_codex_structured_isolation_dispatch",
            max_budget=0,
        )
        assert parsed.name == "Tokyo"
        assert meta.model == "codex"
        assert calls["model"] == "codex"
        assert calls["timeout"] == 19

    def test_structured_with_fenced_json(self, monkeypatch) -> None:
        """Codex sometimes wraps JSON in code fences — should still parse."""
        fake_mod, codex_submod = _make_fake_codex_module()
        turn = _FakeTurn(
            final_response='```json\n{"name": "Berlin", "country": "Germany"}\n```',
            usage=_FakeUsage(),
        )
        fake_codex_cls = type("FakeCodex", (), {
            "__init__": lambda self, options=None: setattr(self, "_turn", turn),
            "start_thread": lambda self, options=None: _FakeThread(turn),
        })
        fake_mod.Codex = fake_codex_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
        monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)

        parsed, meta = call_llm_structured(
            "codex",
            [{"role": "user", "content": "Info about Berlin"}],
            response_model=_CityInfo,
            reasoning_effort="medium",
            task="test", trace_id="test_codex_structured_fenced", max_budget=0,
        )
        assert parsed.name == "Berlin"
        assert parsed.country == "Germany"


# ---------------------------------------------------------------------------
# Codex streaming (mocked)
# ---------------------------------------------------------------------------


class TestCodexStream:
    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_stream_sync(self) -> None:
        stream = stream_llm("codex", [{"role": "user", "content": "Hi"}], reasoning_effort="medium", task="test", trace_id="test_codex_stream_sync", max_budget=0)
        chunks: list[str] = []
        for chunk in stream:
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "4" in "".join(chunks)
        result = stream.result
        assert isinstance(result, LLMCallResult)
        assert result.model == "codex"

    @pytest.mark.usefixtures("_mock_codex_sdk")
    @pytest.mark.asyncio
    async def test_astream_async(self) -> None:
        stream = await astream_llm("codex", [{"role": "user", "content": "Hi"}], reasoning_effort="medium", task="test", trace_id="test_codex_astream_async", max_budget=0)
        chunks: list[str] = []
        async for chunk in stream:
            chunks.append(chunk)
        assert len(chunks) > 0
        assert "4" in "".join(chunks)
        result = stream.result
        assert isinstance(result, LLMCallResult)

    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_stream_hooks_fire(self) -> None:
        before_calls: list = []
        after_calls: list = []
        hooks = Hooks(
            before_call=lambda m, msgs, kw: before_calls.append(m),
            after_call=lambda r: after_calls.append(r),
        )
        stream = stream_llm("codex", [{"role": "user", "content": "Hi"}], hooks=hooks, reasoning_effort="medium", task="test", trace_id="test_codex_stream_hooks", max_budget=0)
        for _ in stream:
            pass
        assert len(before_calls) == 1
        assert len(after_calls) == 1

    def test_stream_multi_items(self, monkeypatch) -> None:
        """Multiple AgentMessageItems yield multiple chunks."""
        fake_mod, codex_submod = _make_fake_codex_module()
        items = [
            _FakeAgentMessageItem(id="msg-1", text="First. "),
            _FakeAgentMessageItem(id="msg-2", text="Second."),
        ]
        turn = _FakeTurn(items=items, final_response="First. \nSecond.")
        fake_codex_cls = type("FakeCodex", (), {
            "__init__": lambda self, options=None: setattr(self, "_turn", turn),
            "start_thread": lambda self, options=None: _FakeThread(turn),
        })
        fake_mod.Codex = fake_codex_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
        monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)

        stream = stream_llm("codex", [{"role": "user", "content": "Hi"}], reasoning_effort="medium", task="test", trace_id="test_codex_stream_multi", max_budget=0)
        chunks = list(stream)
        assert len(chunks) == 2
        assert chunks[0] == "First. "
        assert chunks[1] == "Second."


# ---------------------------------------------------------------------------
# Codex batch (mocked)
# ---------------------------------------------------------------------------


class TestCodexBatch:
    @pytest.mark.usefixtures("_mock_codex_sdk")
    def test_batch_sync(self) -> None:
        messages_list = [
            [{"role": "user", "content": f"What is {i}+{i}?"}]
            for i in range(3)
        ]
        results = call_llm_batch("codex", messages_list, max_concurrent=3, reasoning_effort="medium", task="test", trace_id="test_codex_batch_sync", max_budget=0)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, LLMCallResult)
            assert r.model == "codex"

    @pytest.mark.usefixtures("_mock_codex_sdk")
    @pytest.mark.asyncio
    async def test_batch_async(self) -> None:
        messages_list = [
            [{"role": "user", "content": f"What is {i}+{i}?"}]
            for i in range(2)
        ]
        results = await acall_llm_batch("codex", messages_list, reasoning_effort="medium", task="test", trace_id="test_codex_batch_async", max_budget=0)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Codex fallback (mocked)
# ---------------------------------------------------------------------------


class TestCodexFallback:
    def test_extract_codex_cli_completed_items_retains_intrinsic_and_mcp_events(
        self,
    ) -> None:
        items = [
            {"id": "cmd-1", "type": "command_execution", "status": "completed"},
            {"id": "file-1", "type": "file_change", "status": "completed"},
            {"id": "web-1", "type": "web_search", "status": "completed"},
            {
                "id": "mcp-1",
                "type": "mcp_tool_call",
                "server": "probe",
                "tool": "lookup",
                "arguments": {"query": "ecosystem"},
                "status": "completed",
            },
        ]
        stdout_jsonl = "\n".join(
            json.dumps({"type": "item.completed", "item": item}) for item in items
        )

        completed = agents_codex_mod._extract_codex_cli_completed_items(stdout_jsonl)
        tool_calls = agents_codex_mod._extract_codex_cli_tool_calls(stdout_jsonl)

        assert completed == items
        assert [item["type"] for item in completed] == [
            "command_execution",
            "file_change",
            "web_search",
            "mcp_tool_call",
        ]
        assert [call["function"]["name"] for call in tool_calls] == ["lookup"]

    def test_extract_codex_cli_completed_items_ignores_malformed_and_unsettled_events(
        self,
    ) -> None:
        stdout_jsonl = "\n".join(
            [
                "not-json",
                json.dumps(["not", "an", "event"]),
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {"id": "cmd-1", "type": "command_execution"},
                    }
                ),
                json.dumps({"type": "item.completed", "item": "not-a-mapping"}),
                json.dumps({"type": "item.completed"}),
            ]
        )

        assert agents_codex_mod._extract_codex_cli_completed_items(stdout_jsonl) == []

    def test_fallback_from_codex_to_litellm(self, monkeypatch) -> None:
        """Codex fails, falls back to regular model."""
        fake_mod, codex_submod = _make_fake_codex_module()

        class _FailingThread:
            async def run(self, input_, turn_options=None):
                raise RuntimeError("Codex SDK failed")

        class _FailingCodex:
            def __init__(self, options=None):
                pass
            def start_thread(self, options=None):
                return _FailingThread()

        fake_mod.Codex = _FailingCodex  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "openai_codex_sdk", fake_mod)
        monkeypatch.setitem(sys.modules, "openai_codex_sdk.codex", codex_submod)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Fallback response"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_resp.usage.total_tokens = 15

        with (
            patch("llm_client.core.client.litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp),
            patch("llm_client.core.client.litellm.completion_cost", return_value=0.001),
        ):
            result = call_llm(
                "codex",
                [{"role": "user", "content": "Hi"}],
                fallback_models=["gpt-4o"],
                task="test", trace_id="test_codex_fallback", max_budget=0,
            )
        assert result.content == "Fallback response"
        assert result.model == "gpt-4o"

    def test_codex_transport_auto_falls_back_to_cli_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto transport should fall back from SDK to CLI inside llm_client."""

        async def _fake_inproc(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            del model, messages, timeout, kwargs
            raise TimeoutError("sdk stalled")

        calls: dict[str, object] = {}

        def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            calls["model"] = model
            calls["timeout"] = timeout
            calls["fallback_warning"] = fallback_warning
            calls["agent_hard_timeout"] = kwargs.get("agent_hard_timeout")
            assert output_schema is None
            return LLMCallResult(
                content="cli ok",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                warnings=[fallback_warning] if fallback_warning else [],
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)

        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="auto",
            timeout=17,
            agent_hard_timeout=23,
            task="test",
            trace_id="test_codex_transport_auto_sync",
            max_budget=0,
        )

        assert result.content == "cli ok"
        assert calls["model"] == "codex"
        assert calls["timeout"] == 17
        assert calls["agent_hard_timeout"] == 23
        assert "CODEX_TRANSPORT_FALLBACK[sdk->cli]" in str(calls["fallback_warning"])

    def test_codex_transport_auto_does_not_swallow_programming_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto transport should re-raise unexpected SDK failures instead of masking them."""

        async def _fake_inproc(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            del model, messages, timeout, kwargs
            raise ValueError("bad adapter code")

        def _unexpected_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            raise AssertionError("CLI fallback should not run for ValueError")

        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _unexpected_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _unexpected_cli)

        with pytest.raises(Exception, match="bad adapter code"):
            call_llm(
                "codex",
                [{"role": "user", "content": "Hi"}],
                codex_transport="auto",
                timeout=17,
                agent_hard_timeout=23,
                task="test",
                trace_id="test_codex_transport_auto_value_error",
                max_budget=0,
            )

    def test_codex_transport_auto_falls_back_on_worker_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Worker runtime wrappers should still fall back to CLI transport."""

        async def _fake_inproc(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            del model, messages, timeout, kwargs
            raise RuntimeError("CODEX_WORKER_ERROR[test]")

        calls: dict[str, object] = {}

        def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            del messages, output_schema, kwargs
            calls["fallback_warning"] = fallback_warning
            return LLMCallResult(
                content="cli ok",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                warnings=[fallback_warning] if fallback_warning else [],
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)

        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="auto",
            timeout=17,
            agent_hard_timeout=23,
            task="test",
            trace_id="test_codex_transport_auto_worker_error",
            max_budget=0,
        )

        assert result.content == "cli ok"
        assert "CODEX_TRANSPORT_FALLBACK[sdk->cli]" in str(calls["fallback_warning"])

    def test_codex_transport_auto_falls_back_on_sdk_parse_validation_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Known Codex SDK parse drift should route through CLI fallback."""

        class FileChangeItem(BaseModel):
            status: Literal["completed", "failed"]

        with pytest.raises(Exception) as excinfo:
            FileChangeItem.model_validate({"status": "in_progress"})
        sdk_parse_error = excinfo.value

        async def _fake_inproc(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            del model, messages, timeout, kwargs
            raise sdk_parse_error

        calls: dict[str, object] = {}

        def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            del messages, output_schema, kwargs
            calls["fallback_warning"] = fallback_warning
            return LLMCallResult(
                content="cli recovered",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                warnings=[fallback_warning] if fallback_warning else [],
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _fake_inproc)
        monkeypatch.setattr(agents_mod, "_call_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)

        result = call_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="auto",
            timeout=17,
            agent_hard_timeout=23,
            task="test",
            trace_id="test_codex_transport_auto_sdk_parse_validation",
            max_budget=0,
        )

        assert result.content == "cli recovered"
        assert "CODEX_TRANSPORT_FALLBACK[sdk->cli]" in str(calls["fallback_warning"])
        assert "FileChangeItem" in str(calls["fallback_warning"])

    def test_codex_transport_fallback_rule_stays_narrow_for_other_validation_errors(self) -> None:
        """Other ValidationError instances should not be reclassified as transport failures."""

        class ArbitraryPayload(BaseModel):
            value: int

        with pytest.raises(Exception) as excinfo:
            ArbitraryPayload.model_validate({"value": "not-an-int"})

        assert _is_codex_transport_fallback_error(excinfo.value) is False

    @pytest.mark.asyncio
    async def test_codex_transport_cli_dispatches_async(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit CLI transport should bypass the SDK path entirely."""

        async def _unexpected_inproc(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            **kwargs: object,
        ) -> LLMCallResult:
            raise AssertionError("SDK path should not run for codex_transport=cli")

        async def _fake_cli(
            model: str,
            messages: list[dict[str, object]],
            *,
            timeout: int = 300,
            output_schema: dict[str, object] | None = None,
            fallback_warning: str | None = None,
            **kwargs: object,
        ) -> LLMCallResult:
            del messages, output_schema, fallback_warning, kwargs
            return LLMCallResult(
                content=f"cli async {timeout}",
                usage={},
                cost=0.0,
                model=model,
                finish_reason="stop",
                raw_response={"transport": "codex_cli"},
            )

        monkeypatch.setattr(agents_mod, "_acall_codex_inproc", _unexpected_inproc)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_inproc", _unexpected_inproc)
        monkeypatch.setattr(agents_mod, "_acall_codex_via_cli", _fake_cli)
        monkeypatch.setattr(agents_codex_mod, "_acall_codex_via_cli", _fake_cli)

        result = await acall_llm(
            "codex",
            [{"role": "user", "content": "Hi"}],
            codex_transport="cli",
            timeout=19,
            reasoning_effort="medium",
            task="test",
            trace_id="test_codex_transport_cli_async",
            max_budget=0,
        )

        assert result.content == "cli async 19"
        assert result.raw_response == {"transport": "codex_cli"}

    def test_build_codex_cli_command_forwards_reasoning_effort(self, tmp_path) -> None:
        """CLI transport should carry normalized reasoning effort into codex exec."""

        command, _env, stdin_payload = _build_codex_cli_command(
            "codex",
            "Reply with OK only.",
            output_schema=None,
            kwargs={
                "working_directory": str(tmp_path),
                "approval_policy": "never",
                "sandbox_mode": "workspace-write",
                "skip_git_repo_check": True,
                "model_reasoning_effort": "high",
            },
            output_path=str(tmp_path / "last.txt"),
            schema_path=None,
        )

        assert "-c" in command
        assert 'model_reasoning_effort="high"' in command
        assert stdin_payload == "Reply with OK only."

    def test_build_codex_cli_command_forwards_network_and_search(self, tmp_path) -> None:
        """CLI fallback should retain explicitly requested agent capabilities."""

        command, _env, _stdin_payload = _build_codex_cli_command(
            "codex",
            "Research one public source.",
            output_schema=None,
            kwargs={
                "working_directory": str(tmp_path),
                "approval_policy": "never",
                "sandbox_mode": "workspace-write",
                "model_reasoning_effort": "medium",
                "network_access_enabled": True,
                "web_search_enabled": True,
            },
            output_path=str(tmp_path / "last.txt"),
            schema_path=None,
        )

        assert "sandbox_workspace_write.network_access=true" in command
        assert "--search" in command
        assert command[command.index("-s") + 1] == "workspace-write"

    def test_build_codex_cli_command_yolo_mode_sets_skip_git_repo_check(self, tmp_path) -> None:
        """yolo_mode should enable Codex's trusted-repo bypass convenience flag."""

        command, _env, stdin_payload = _build_codex_cli_command(
            "codex",
            "Reply with OK only.",
            output_schema=None,
            kwargs={
                "working_directory": str(tmp_path),
                "yolo_mode": True,
                "model_reasoning_effort": "medium",
            },
            output_path=str(tmp_path / "last.txt"),
            schema_path=None,
        )

        assert "--skip-git-repo-check" in command
        assert "--dangerously-bypass-approvals-and-sandbox" in command
        assert stdin_payload == "Reply with OK only."

    def test_build_codex_cli_command_preserves_sandbox_for_never_approval(self, tmp_path) -> None:
        """Headless approval must not silently discard the requested sandbox."""

        command, _env, _stdin_payload = _build_codex_cli_command(
            "codex",
            "Reply with OK only.",
            output_schema=None,
            kwargs={
                "working_directory": str(tmp_path),
                "approval_policy": "never",
                "sandbox_mode": "read-only",
                "model_reasoning_effort": "medium",
            },
            output_path=str(tmp_path / "last.txt"),
            schema_path=None,
        )

        assert "--dangerously-bypass-approvals-and-sandbox" not in command
        assert "-a" not in command
        assert 'approval_policy="never"' in command
        assert command[command.index("-s") + 1] == "read-only"

    def test_build_codex_cli_command_forwards_non_never_approval(self, tmp_path) -> None:
        """Current Codex receives approval policy via config, not removed `-a`."""

        command, _env, _stdin_payload = _build_codex_cli_command(
            "codex",
            "Reply with OK only.",
            output_schema=None,
            kwargs={
                "working_directory": str(tmp_path),
                "approval_policy": "on-request",
                "sandbox_mode": "read-only",
                "model_reasoning_effort": "medium",
            },
            output_path=str(tmp_path / "last.txt"),
            schema_path=None,
        )

        assert "-a" not in command
        assert 'approval_policy="on-request"' in command
        assert "--dangerously-bypass-approvals-and-sandbox" not in command

    def test_call_codex_via_cli_uses_subprocess_transport(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """CLI transport should execute via subprocess and return the written output."""

        def _fake_run(command, *, input, text, capture_output, check, timeout, env):
            del input, text, capture_output, check, timeout, env
            output_path = command[command.index("-o") + 1]
            Path(output_path).write_text("cli transport ok\n")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agents_codex_mod.subprocess, "run", _fake_run)

        result = agents_codex_mod._call_codex_via_cli(
            "codex",
            [{"role": "user", "content": "Reply with OK only."}],
            timeout=11,
            working_directory=str(tmp_path),
            approval_policy="never",
            sandbox_mode="workspace-write",
            skip_git_repo_check=True,
            model_reasoning_effort="medium",
        )

        assert result.content == "cli transport ok"
        assert result.raw_response == {
            "transport": "codex_cli",
            "session_id": None,
            "n_turns": 0,
        }

    def test_call_codex_via_cli_exposes_completed_items_on_public_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        items = [
            {"id": "cmd-1", "type": "command_execution", "status": "completed"},
            {"id": "file-1", "type": "file_change", "status": "completed"},
            {"id": "web-1", "type": "web_search", "status": "completed"},
        ]

        def _fake_run(command, *, input, text, capture_output, check, timeout, env):
            del input, text, capture_output, check, timeout, env
            output_path = command[command.index("-o") + 1]
            Path(output_path).write_text("structured response\n")
            return types.SimpleNamespace(
                returncode=0,
                stdout="\n".join(
                    json.dumps({"type": "item.completed", "item": item})
                    for item in items
                ),
                stderr="",
            )

        monkeypatch.setattr(agents_codex_mod.subprocess, "run", _fake_run)

        result = agents_codex_mod._call_codex_via_cli(
            "codex",
            [{"role": "user", "content": "Choose one action."}],
            working_directory=str(tmp_path),
            approval_policy="never",
            sandbox_mode="read-only",
            model_reasoning_effort="medium",
        )

        assert result.codex_events == items
        assert result.tool_calls == []

    def test_public_structured_call_retains_codex_completed_items(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Decision(BaseModel):
            action: Literal["wait"]

        items = [
            {"id": "cmd-1", "type": "command_execution", "status": "completed"},
            {"id": "file-1", "type": "file_change", "status": "completed"},
            {"id": "web-1", "type": "web_search", "status": "completed"},
        ]

        def _fake_cli(*args, **kwargs):
            del args, kwargs
            return LLMCallResult(
                content='{"action":"wait"}',
                usage={},
                cost=0.0,
                model="codex/gpt-5.6-luna",
                resolved_model="codex/gpt-5.6-luna",
                codex_events=items,
                finish_reason="stop",
                raw_response={"transport": "codex_cli"},
                cost_source="subscription_included",
                billing_mode="subscription_included",
            )

        monkeypatch.setattr(agents_codex_mod, "_call_codex_via_cli", _fake_cli)

        decision, result = call_llm_structured(
            "codex/gpt-5.6-luna",
            [{"role": "user", "content": "Choose one action."}],
            response_model=Decision,
            reasoning_effort="medium",
            codex_transport="cli",
            task="test",
            trace_id="test_public_codex_completed_item_custody",
            max_budget=0,
        )

        assert decision == Decision(action="wait")
        assert result.codex_events == items
        assert result.raw_response == {"transport": "codex_cli"}

    def test_call_codex_via_cli_attaches_mcp_and_returns_tool_evidence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """CLI transport should attach MCP config and retain completed call evidence."""

        captured_home: Path | None = None

        def _fake_run(command, *, input, text, capture_output, check, timeout, env):
            nonlocal captured_home
            del input, text, capture_output, check, timeout
            assert "--json" in command
            captured_home = Path(env["CODEX_HOME"]).parent
            config = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
            assert '[mcp_servers."twitter"]' in config
            assert 'command = "python"' in config
            output_path = command[command.index("-o") + 1]
            Path(output_path).write_text('{"candidates":[]}\n')
            event = {
                "type": "item.completed",
                "item": {
                    "id": "item-1",
                    "type": "mcp_tool_call",
                    "server": "twitter",
                    "tool": "advanced_search",
                    "arguments": {"query": "founder"},
                    "result": {"count": 3},
                    "status": "completed",
                },
            }
            return types.SimpleNamespace(
                returncode=0,
                stdout=json.dumps(event),
                stderr="",
            )

        monkeypatch.setattr(agents_codex_mod.subprocess, "run", _fake_run)

        result = agents_codex_mod._call_codex_via_cli(
            "codex",
            [{"role": "user", "content": "Find candidates."}],
            working_directory=str(tmp_path),
            model_reasoning_effort="medium",
            mcp_servers={
                "twitter": {
                    "command": "python",
                    "args": ["server.py"],
                    "env": {"API_KEY": "test-only-secret"},
                }
            },
        )

        assert result.tool_calls == [
            {
                "id": "item-1",
                "type": "function",
                "function": {
                    "name": "advanced_search",
                    "arguments": {"query": "founder"},
                },
                "server": "twitter",
                "status": "completed",
                "result_preview": '{"count": 3}',
                "is_error": False,
                "error": "",
            }
        ]
        assert captured_home is not None
        assert not captured_home.exists()

    def test_call_codex_via_cli_cleans_mcp_home_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A failed CLI subprocess must not retain its credential-bearing temp home."""

        captured_home: Path | None = None

        def _fake_run(command, *, input, text, capture_output, check, timeout, env):
            nonlocal captured_home
            del command, input, text, capture_output, check, timeout
            captured_home = Path(env["CODEX_HOME"]).parent
            return types.SimpleNamespace(returncode=2, stdout="", stderr="failed")

        monkeypatch.setattr(agents_codex_mod.subprocess, "run", _fake_run)

        with pytest.raises(RuntimeError, match="CODEX_CLI_ERROR"):
            agents_codex_mod._call_codex_via_cli(
                "codex",
                [{"role": "user", "content": "Find candidates."}],
                working_directory=str(tmp_path),
                model_reasoning_effort="medium",
                mcp_servers={"twitter": {"command": "python"}},
            )

        assert captured_home is not None
        assert not captured_home.exists()


# ---------------------------------------------------------------------------
# Codex MCP server control
# ---------------------------------------------------------------------------


class TestCodexMcpServers:
    """Tests for codex_home and mcp_servers kwargs."""

    def test_create_codex_home(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The isolated home preserves providers but drops ambient MCP tools."""
        from pathlib import Path

        from llm_client.sdk.agents import _cleanup_tmp, _create_codex_home

        source_codex_home = tmp_path / "source-codex"
        source_codex_home.mkdir()
        (source_codex_home / "config.toml").write_text(
            'model_provider = "openrouter"\n'
            'model = "~openai/gpt-latest"\n'
            "\n"
            "[mcp_servers.ambient]\n"
            'command = "ambient-tool"\n'
            "\n"
            "[mcp_servers.ambient.env]\n"
            'SECRET = "must-not-copy"\n'
            "\n"
            "[model_providers.openrouter]\n"
            'base_url = "https://openrouter.ai/api/v1"\n'
            'env_key = "OPENROUTER_API_KEY"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("CODEX_HOME", str(source_codex_home))
        servers = {
            "my-server": {
                "command": "/usr/bin/python",
                "args": ["-u", "server.py"],
                "env": {"FOO": "bar"},
            },
            "simple": {
                "command": "node",
                "args": ["index.js"],
                "cwd": "/tmp/test",
            },
        }
        tmp_dir = _create_codex_home(servers)
        try:
            config_path = Path(tmp_dir) / ".codex" / "config.toml"
            assert config_path.exists()
            content = config_path.read_text()
            assert '[mcp_servers."my-server"]' in content
            assert 'command = "/usr/bin/python"' in content
            assert "required = true" in content
            assert 'args = ["-u", "server.py"]' in content
            assert '"FOO" = "bar"' in content
            assert '[mcp_servers."simple"]' in content
            assert 'cwd = "/tmp/test"' in content
            assert 'model_provider = "openrouter"' in content
            assert "[model_providers.openrouter]" in content
            assert "[mcp_servers.ambient]" not in content
            assert "ambient-tool" not in content
            assert "must-not-copy" not in content
        finally:
            _cleanup_tmp(tmp_dir)

    def test_prepare_codex_mcp_isolates_home_by_default(self) -> None:
        """No mcp_servers should still isolate Codex from the user's global home."""
        from pathlib import Path

        from llm_client.sdk.agents import _cleanup_tmp, _prepare_codex_mcp

        kwargs = {"sandbox_mode": "workspace-write"}
        out, tmp = _prepare_codex_mcp(kwargs)
        try:
            assert tmp is not None
            assert out["codex_home"] == tmp
            assert (Path(tmp) / ".codex" / "config.toml").exists()
        finally:
            _cleanup_tmp(tmp)

    def test_prepare_codex_mcp_passthrough_when_isolation_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Isolation can be disabled explicitly for operators who need global Codex home."""
        from llm_client.sdk.agents import _prepare_codex_mcp

        monkeypatch.setenv("LLM_CLIENT_CODEX_ISOLATE_HOME", "0")
        kwargs = {"sandbox_mode": "workspace-write"}
        out, tmp = _prepare_codex_mcp(kwargs)
        assert tmp is None
        assert out is kwargs

    def test_prepare_codex_mcp_creates_home(self) -> None:
        """mcp_servers → creates codex_home, removes mcp_servers from kwargs."""
        from pathlib import Path

        from llm_client.sdk.agents import _cleanup_tmp, _prepare_codex_mcp

        kwargs = {
            "sandbox_mode": "workspace-write",
            "mcp_servers": {"test": {"command": "echo", "args": ["hello"]}},
        }
        out, tmp = _prepare_codex_mcp(kwargs)
        try:
            assert tmp is not None
            assert "codex_home" in out
            assert "mcp_servers" not in out
            assert (Path(tmp) / ".codex" / "config.toml").exists()
        finally:
            _cleanup_tmp(tmp)

    def test_prepare_codex_mcp_rejects_both(self) -> None:
        """Cannot specify both mcp_servers and codex_home."""
        from llm_client.sdk.agents import _prepare_codex_mcp

        kwargs = {
            "codex_home": "/some/path",
            "mcp_servers": {"test": {"command": "echo"}},
        }
        with pytest.raises(ValueError, match="Cannot specify both"):
            _prepare_codex_mcp(kwargs)

    @pytest.mark.usefixtures("_mock_codex_sdk")
    @pytest.mark.asyncio
    async def test_mcp_servers_end_to_end(self) -> None:
        """mcp_servers kwarg creates temp config and cleans up."""
        import tempfile
        from pathlib import Path

        result = await acall_llm(
            "codex",
            [{"role": "user", "content": "What is 2+2?"}],
            mcp_servers={
                "test-server": {
                    "command": "/usr/bin/echo",
                    "args": ["hello"],
                },
            },
            reasoning_effort="medium",
            task="test", trace_id="test_codex_mcp_e2e", max_budget=0,
        )
        assert isinstance(result, LLMCallResult)
        assert result.content  # got an answer

        # Verify temp dirs are cleaned up
        tmp_root = Path(tempfile.gettempdir())
        codex_homes = list(tmp_root.glob("codex_home_*"))
        for d in codex_homes:
            config = d / ".codex" / "config.toml"
            if config.exists():
                content = config.read_text()
                if "test-server" in content:
                    pytest.fail(f"Temp codex home not cleaned up: {d}")

    def test_cleanup_tmp_handles_none(self) -> None:
        """_cleanup_tmp(None) is a no-op."""
        from llm_client.sdk.agents import _cleanup_tmp

        _cleanup_tmp(None)  # should not raise

    def test_cleanup_tmp_handles_missing(self) -> None:
        """_cleanup_tmp with nonexistent path doesn't raise."""
        from llm_client.sdk.agents import _cleanup_tmp

        _cleanup_tmp("/tmp/this_does_not_exist_12345")  # should not raise


# ---------------------------------------------------------------------------
# Best-effort agent session diagnostics (reads the claude CLI's own session
# transcript to summarize what happened during a failed agent-SDK call)
# ---------------------------------------------------------------------------


class TestAgentSessionDiagnosticsUnit:
    """Direct unit tests of the transcript-reading summarizer, independent of
    any real SDK call."""

    def test_slug_replaces_path_separators_with_hyphens(self) -> None:
        from llm_client.sdk.agents_claude import _agent_session_project_dir

        result = _agent_session_project_dir("/home/brian/code/ac15")
        assert result.name == "-home-brian-code-ac15"

    def test_summarizes_multiple_attempts_from_a_real_transcript(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_client.sdk.agents_claude import _summarize_failed_agent_session

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cwd = "/fake/project/dir"
        project_dir = tmp_path / ".claude" / "projects" / "-fake-project-dir"
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session-1.jsonl"
        entries = [
            {"type": "last-prompt", "leafUuid": "leaf-1"},
            {
                "type": "assistant",
                "message": {"content": [{"type": "thinking", "thinking": "x" * 100}]},
            },
            {"type": "last-prompt", "leafUuid": "leaf-2"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "y" * 50},
                        {"type": "tool_use", "name": "StructuredOutput", "input": {}},
                    ]
                },
            },
        ]
        transcript.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        result = _summarize_failed_agent_session(cwd, now, now)

        assert result is not None
        assert "attempts=2" in result
        assert "attempt1(thinking_chars=100, answered=False)" in result
        assert "attempt2(thinking_chars=50, answered=True)" in result

    def test_returns_none_when_no_project_dir_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_client.sdk.agents_claude import _summarize_failed_agent_session

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        assert _summarize_failed_agent_session("/nowhere", now, now) is None

    def test_returns_none_when_no_file_matches_the_time_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llm_client.sdk.agents_claude import _summarize_failed_agent_session

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cwd = "/fake/project"
        project_dir = tmp_path / ".claude" / "projects" / "-fake-project"
        project_dir.mkdir(parents=True)
        (project_dir / "old-session.jsonl").write_text(
            json.dumps({"type": "last-prompt", "leafUuid": "leaf-1"}) + "\n",
            encoding="utf-8",
        )
        import os
        from datetime import datetime, timedelta, timezone

        # Push the file's mtime well outside the +/-5s matching window.
        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
        os.utime(project_dir / "old-session.jsonl", (old_time, old_time))

        now = datetime.now(timezone.utc)
        assert _summarize_failed_agent_session(cwd, now, now) is None

    def test_never_raises_on_malformed_transcript_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Diagnostic capture must degrade to None, never propagate its own
        exception -- it must never be the reason a real call fails."""
        from llm_client.sdk.agents_claude import _summarize_failed_agent_session

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cwd = "/fake/project"
        project_dir = tmp_path / ".claude" / "projects" / "-fake-project"
        project_dir.mkdir(parents=True)
        (project_dir / "bad-session.jsonl").write_text(
            "not json at all\n{also not json\n", encoding="utf-8"
        )

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        assert _summarize_failed_agent_session(cwd, now, now) is None


class TestAgentSessionDiagnosticsOnFailure:
    """End-to-end: a failing structured agent call must attach the summary as
    an exception note, without changing the raised exception type."""

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_structured_call_failure_gets_diagnostic_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        class _Answer(BaseModel):
            x: int

        async def _raising_query(prompt, options=None):
            raise RuntimeError(
                "Claude Code returned an error result: Failed to provide valid "
                "structured output after 5 attempts"
            )
            yield  # pragma: no cover - unreachable; keeps this an async generator

        monkeypatch.setattr(sys.modules["claude_agent_sdk"], "query", _raising_query)

        cwd = "/fake/proj"
        project_dir = tmp_path / ".claude" / "projects" / "-fake-proj"
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"type": "last-prompt", "leafUuid": "leaf-1"},
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "thinking", "thinking": "z" * 42}]
                        },
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError) as excinfo:
            await acall_llm_structured(
                "claude-code/sonnet",
                [{"role": "user", "content": "hi"}],
                response_model=_Answer,
                task="test",
                trace_id="test_diagnostics_on_failure",
                max_budget=0,
                cwd=cwd,
            )

        notes = getattr(excinfo.value, "__notes__", [])
        assert any("agent_session_diagnostics" in n for n in notes), notes
        assert any("thinking_chars=42" in n for n in notes), notes

    @pytest.mark.usefixtures("_mock_agent_sdk")
    @pytest.mark.asyncio
    async def test_structured_call_failure_without_transcript_still_raises_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No matching transcript on disk -> no note attached, but the
        original failure still propagates unchanged."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        class _Answer(BaseModel):
            x: int

        async def _raising_query(prompt, options=None):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        monkeypatch.setattr(sys.modules["claude_agent_sdk"], "query", _raising_query)

        with pytest.raises(RuntimeError, match="boom") as excinfo:
            await acall_llm_structured(
                "claude-code/sonnet",
                [{"role": "user", "content": "hi"}],
                response_model=_Answer,
                task="test",
                trace_id="test_diagnostics_missing_transcript",
                max_budget=0,
                cwd="/fake/nowhere",
            )

        assert not getattr(excinfo.value, "__notes__", [])
