"""Thread-safety controls for Instructor structured-client construction.

# mock-ok: deterministically widens the public Instructor construction seam.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import instructor

from llm_client.execution.structured_runtime import _instructor_from_litellm


def test_instructor_construction_is_serialized(monkeypatch) -> None:
    """Concurrent public client construction never overlaps."""

    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_from_litellm(create_fn: object) -> object:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with state_lock:
            active -= 1
        return create_fn

    monkeypatch.setattr(instructor, "from_litellm", fake_from_litellm)
    values = list(range(12))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_instructor_from_litellm, values))

    assert results == values
    assert maximum_active == 1


def test_runtime_does_not_depend_on_instructor_v2() -> None:
    """The supported 1.x environment can import the public construction seam."""

    assert callable(_instructor_from_litellm)
