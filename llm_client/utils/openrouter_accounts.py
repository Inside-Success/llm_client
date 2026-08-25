"""Resolve which OpenRouter billing account owns the calling repository's spend.

Account selection is derived from the repository that owns the running code
rather than from process environment set by hand.  A control that depends on
someone remembering to switch accounts before working is not a control, and the
failure is silent: the wrong account is billed and nothing reports it.

Resolution order, first match wins:

1. ``LLM_CLIENT_OPENROUTER_ACCOUNT`` -- explicit override for CI and one-off runs.
2. ``repository_accounts`` -- exact ``owner/repo`` from the Git remote.  This is
   how repositories personally owned but worked on for a client are declared.
3. ``remote_owner_accounts`` -- the Git remote's owner (e.g. ``inside-success``).
4. ``default_account`` -- fail safe.

Directory paths are deliberately NOT a routing signal.  Client repositories are
symlinked into the client workspace while their real checkouts live in the
personal tree, so a path rule silently misroutes exactly the repositories that
matter most.  Git remote identity survives symlinks, worktrees, and relocation.
"""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Final

DEFAULT_ROUTING_PATH: Final = Path(__file__).resolve().parent.parent / "data" / "openrouter_account_routing.json"
ROUTING_PATH_ENV: Final = "LLM_CLIENT_OPENROUTER_ROUTING_FILE"
ACCOUNT_OVERRIDE_ENV: Final = "LLM_CLIENT_OPENROUTER_ACCOUNT"

PERSONAL_ACCOUNT: Final = "personal"
INSIDE_SUCCESS_ACCOUNT: Final = "inside_success"

#: Per-account credential variables. An account with no variable set falls back
#: to the historical single-key behaviour, so adopting this is not a flag day.
ACCOUNT_KEY_ENV: Final[dict[str, str]] = {
    PERSONAL_ACCOUNT: "OPENROUTER_API_KEY_PERSONAL",
    INSIDE_SUCCESS_ACCOUNT: "OPENROUTER_API_KEY_INSIDE_SUCCESS",
}

_REMOTE_RE: Final = re.compile(
    r"""
    (?:git@[^:]+:|https?://[^/]+/|ssh://git@[^/]+/)
    (?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$
    """,
    re.VERBOSE,
)


class AccountRoutingError(ValueError):
    """Raised when routing configuration cannot be trusted to bill correctly."""


def _load_routing(path: Path | None = None) -> dict[str, Any]:
    """Read the routing table, failing loud rather than defaulting silently."""

    resolved = path or Path(os.environ.get(ROUTING_PATH_ENV, str(DEFAULT_ROUTING_PATH)))
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AccountRoutingError(f"OpenRouter account routing table missing: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise AccountRoutingError(f"OpenRouter account routing table is not valid JSON: {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AccountRoutingError(f"OpenRouter account routing table must be a JSON object: {resolved}")
    default_account = payload.get("default_account")
    if not isinstance(default_account, str) or not default_account:
        raise AccountRoutingError(f"OpenRouter account routing table needs a non-empty default_account: {resolved}")
    return payload


def parse_remote_identity(remote_url: str) -> tuple[str, str] | None:
    """Return lowercased ``(owner, repo)`` for a Git remote URL, or None."""

    match = _REMOTE_RE.search(remote_url.strip())
    if match is None:
        return None
    return match.group("owner").lower(), match.group("repo").lower()


@functools.lru_cache(maxsize=32)
def _git_remote_url(cwd: str) -> str | None:
    """Read origin's URL, tolerating non-repository and git-less environments."""

    try:
        completed = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, NotADirectoryError, subprocess.CalledProcessError):
        return None
    url = completed.stdout.strip()
    return url or None


def resolve_account(cwd: str | Path | None = None, *, routing_path: Path | None = None) -> str:
    """Return the billing account owning LLM spend for the calling repository."""

    override = os.environ.get(ACCOUNT_OVERRIDE_ENV, "").strip()
    routing = _load_routing(routing_path)
    default_account: str = str(routing["default_account"])

    if override:
        known = set(ACCOUNT_KEY_ENV) | {default_account}
        known |= set(routing.get("repository_accounts", {}).values())
        known |= set(routing.get("remote_owner_accounts", {}).values())
        if override not in known:
            raise AccountRoutingError(
                f"{ACCOUNT_OVERRIDE_ENV}={override!r} is not a known account; expected one of {sorted(known)}"
            )
        return override

    remote_url = _git_remote_url(str(cwd or Path.cwd()))
    if remote_url is None:
        return default_account
    identity = parse_remote_identity(remote_url)
    if identity is None:
        return default_account
    owner, repo = identity

    repository_accounts = routing.get("repository_accounts", {})
    if isinstance(repository_accounts, dict):
        mapped = repository_accounts.get(f"{owner}/{repo}")
        if isinstance(mapped, str) and mapped:
            return mapped

    remote_owner_accounts = routing.get("remote_owner_accounts", {})
    if isinstance(remote_owner_accounts, dict):
        mapped = remote_owner_accounts.get(owner)
        if isinstance(mapped, str) and mapped:
            return mapped

    return default_account


def account_api_key(account: str) -> str | None:
    """Return the configured credential for one account, if it has one."""

    env_name = ACCOUNT_KEY_ENV.get(account)
    if env_name is None:
        return None
    value = os.environ.get(env_name, "").strip().strip("\"'")
    return value or None


def routed_openrouter_key(cwd: str | Path | None = None) -> tuple[str, str] | None:
    """Return ``(account, api_key)`` when account routing owns this process's key.

    Returns None when no per-account credential is configured, which leaves the
    historical single-key behaviour untouched.
    """

    account = resolve_account(cwd)
    key = account_api_key(account)
    if key is None:
        return None
    return account, key
