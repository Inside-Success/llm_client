"""Registry for duet ``TaskFamily`` profiles.

The chassis and CLI resolve profiles by name (``task_family="generic"``,
``task_family="plan_doc_review"``, ...). Built-in profiles register themselves
at import via ``llm_client.workflow.profiles``; consumer-owned profiles call
``register_task_family(family)`` from their own initialization code.

Lookup failures are loud — there is no silent fallback to ``generic``. If a
caller asks for an unknown profile, that's a programmer error, not something
to paper over.
"""

from __future__ import annotations

from llm_client.workflow.duet_base import TaskFamily

_REGISTRY: dict[str, TaskFamily] = {}


def register_task_family(family: TaskFamily) -> None:
    """Register a profile. Raises if ``family.name`` is already taken.

    Duplicate registration is a programmer error (likely a copy-paste or an
    import ordering problem), not a silent overwrite.
    """
    if family.name in _REGISTRY:
        raise ValueError(
            f"TaskFamily {family.name!r} already registered. "
            f"Use a distinct name or remove the prior registration."
        )
    _REGISTRY[family.name] = family


def get_task_family(name: str) -> TaskFamily:
    """Resolve a profile by name. Raises if not registered.

    No silent fallback to ``generic`` — an unknown name means the caller
    misspelled the profile or forgot to import the registering module.
    """
    if name not in _REGISTRY:
        available = sorted(_REGISTRY) or ["<none registered yet>"]
        raise KeyError(
            f"TaskFamily {name!r} is not registered. Available: {available}. "
            f"Built-in profiles are registered via llm_client.workflow.profiles; "
            f"ensure that subpackage is imported before lookup."
        )
    return _REGISTRY[name]


def list_task_families() -> list[str]:
    """Return the names of all registered profiles (sorted)."""
    return sorted(_REGISTRY)


def _reset_for_tests() -> None:
    """Test-only hook: clear the registry. Not part of the public API."""
    _REGISTRY.clear()


__all__ = [
    "register_task_family",
    "get_task_family",
    "list_task_families",
]
