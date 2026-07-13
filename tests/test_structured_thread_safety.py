"""Thread-safety of concurrent structured calls.

# mock-ok: validates the runtime seam against patched provider transports

The field failure (grounded-research Session 26): concurrent
``call_llm_structured`` from a ``ThreadPoolExecutor`` died with
``RegistryError: Mode.TOOLS is not registered for provider Provider.OPENAI``
while sequential calls worked. Root cause: instructor's global
``mode_registry`` lazy-loads handlers NON-atomically
(``_lazy_loaders.pop`` -> module import -> ``_handlers`` store), so a second
thread arriving inside that window finds the key in neither dict.

The fix (``_instructor_from_litellm``) serializes client construction and
eagerly warms the default (Provider.OPENAI, Mode.TOOLS) handlers under a
process-wide lock, making every later registry lookup a plain dict read.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_client.execution import structured_runtime as sr
from llm_client.execution.structured_runtime import _call_llm_structured_impl

instructor = pytest.importorskip("instructor")


class _Echo(BaseModel):
    model_seen: str


@pytest.fixture(autouse=True)
def _explicit_test_runtime_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CLIENT_OPENROUTER_ROUTING", "off")
    monkeypatch.setenv("LLM_CLIENT_TIMEOUT_POLICY", "allow")


# ---------------------------------------------------------------------------
# The upstream race, reproduced deterministically
# ---------------------------------------------------------------------------


def test_instructor_lazy_registry_race_reproduces() -> None:
    """Two threads racing a fresh lazy registry hit the pop->store window.

    This documents the S26 mechanism against instructor's real registry class
    (a fresh instance — the global registry is untouched). Thread A blocks
    inside the lazy loader (key already popped, handlers not yet stored);
    thread B then finds the key in neither dict and gets the
    'not registered' failure that surfaced in the field.
    """
    from instructor.v2.core.mode import Mode
    from instructor.v2.core.providers import Provider
    from instructor.v2.core.registry import ModeRegistry

    registry = ModeRegistry()
    in_loader = threading.Event()
    release = threading.Event()

    def loader() -> object:
        in_loader.set()
        assert release.wait(5), "test deadlock: release never set"
        return object()  # stands in for ModeHandlers

    registry.register_lazy(Provider.OPENAI, Mode.TOOLS, loader)

    first_error: list[BaseException] = []

    def first_access() -> None:
        try:
            registry.get_handlers(Provider.OPENAI, Mode.TOOLS)
        except BaseException as exc:  # pragma: no cover - defensive
            first_error.append(exc)

    t1 = threading.Thread(target=first_access)
    t1.start()
    try:
        assert in_loader.wait(5), "loader never entered"
        # The window is open: popped from _lazy_loaders, absent from _handlers.
        with pytest.raises(KeyError, match="not registered"):
            registry.get_handlers(Provider.OPENAI, Mode.TOOLS)
    finally:
        release.set()
        t1.join(5)
    assert not first_error


# ---------------------------------------------------------------------------
# The fix: serialized construction + eager warmup
# ---------------------------------------------------------------------------


def test_warmup_loads_default_handlers_into_global_registry() -> None:
    from instructor.v2.core.mode import Mode
    from instructor.v2.core.providers import Provider
    from instructor.v2.core.registry import mode_registry

    sr._ensure_instructor_registry_loaded()
    assert (Provider.OPENAI, Mode.TOOLS) in mode_registry._handlers


def test_instructor_construction_is_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent _instructor_from_litellm calls never overlap construction."""
    concurrent_now = []
    overlaps: list[int] = []

    def fake_from_litellm(fn: object) -> object:
        concurrent_now.append(1)
        overlaps.append(len(concurrent_now))
        time.sleep(0.02)
        concurrent_now.pop()
        return object()

    monkeypatch.setattr(instructor, "from_litellm", fake_from_litellm)
    monkeypatch.setattr(sr, "_ensure_instructor_registry_loaded", lambda: None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: sr._instructor_from_litellm(object()), range(16)))

    assert overlaps and max(overlaps) == 1, f"construction overlapped: {overlaps}"


# ---------------------------------------------------------------------------
# Two threads, two models, two modes — each result matches its request
# ---------------------------------------------------------------------------


_MODEL_NATIVE = "openrouter/openai/model-native"
_MODEL_INSTRUCTOR = "openrouter/google/model-instructor"


def _tagged_response(model: str) -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = json.dumps({"model_seen": model})
    mock.choices[0].finish_reason = "stop"
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 5
    mock.usage.total_tokens = 15
    return mock


@patch("llm_client.core.client.litellm.completion_cost", return_value=0.001)
@patch("llm_client.core.client.litellm.supports_response_schema")
@patch("llm_client.core.client.litellm.completion")
def test_concurrent_structured_calls_route_to_requested_models(
    mock_comp: MagicMock,
    mock_supports: MagicMock,
    _mock_cost: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two threads / two models / two execution modes: no response crossing.

    One model takes the native-json_schema path, the other is forced onto the
    instructor fallback (supports_response_schema=False). Both transports tag
    their response with the model they were asked for; every threaded call
    must get back its own model's response and identity metadata.
    """
    mock_supports.side_effect = lambda model: model == _MODEL_NATIVE

    def fake_completion(**kwargs: object) -> MagicMock:
        time.sleep(0.01)  # widen the overlap window
        return _tagged_response(str(kwargs["model"]))

    mock_comp.side_effect = fake_completion

    class _FakeInstructorClient:
        class chat:  # noqa: N801 - mirrors instructor's attribute shape
            class completions:  # noqa: N801
                @staticmethod
                def create_with_completion(**kwargs: object) -> tuple[_Echo, MagicMock]:
                    time.sleep(0.01)
                    model = str(kwargs["model"])
                    return _Echo(model_seen=model), _tagged_response(model)

    monkeypatch.setattr(instructor, "from_litellm", lambda fn: _FakeInstructorClient())

    def one_call(model: str) -> tuple[str, object]:
        parsed, meta = _call_llm_structured_impl(
            model,
            [{"role": "user", "content": "tag yourself"}],
            _Echo,
            task="test",
            trace_id=f"structured.threads.{model.rsplit('/', 1)[-1]}",
            max_budget=0,
        )
        return parsed.model_seen, meta

    rounds = 8
    with ThreadPoolExecutor(max_workers=2) as pool:
        native_futures = [pool.submit(one_call, _MODEL_NATIVE) for _ in range(rounds)]
        instructor_futures = [
            pool.submit(one_call, _MODEL_INSTRUCTOR) for _ in range(rounds)
        ]

    for future in native_futures:
        model_seen, meta = future.result()
        assert model_seen == _MODEL_NATIVE
        assert meta.requested_model == _MODEL_NATIVE
        assert meta.resolved_model == _MODEL_NATIVE
    for future in instructor_futures:
        model_seen, meta = future.result()
        assert model_seen == _MODEL_INSTRUCTOR
        assert meta.requested_model == _MODEL_INSTRUCTOR
        assert meta.resolved_model == _MODEL_INSTRUCTOR
