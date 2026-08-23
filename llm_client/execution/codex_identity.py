"""Privacy-bounded identity evidence for ChatGPT-authenticated Codex calls."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class CodexAccountIdentity:
    """Opaque account evidence resolved before a Codex call is dispatched."""

    binding: Literal["explicit", "ambient"]
    account_id_sha256: str | None


def _codex_config_dir(
    kwargs: dict[str, Any],
) -> tuple[Path, Literal["explicit", "ambient"]]:
    explicit_home = kwargs.get("codex_home")
    if explicit_home is not None:
        return Path(str(explicit_home)).expanduser() / ".codex", "explicit"
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser(), "ambient"
    return Path.home() / ".codex", "ambient"


def resolve_codex_account_identity(
    model: str,
    kwargs: dict[str, Any],
) -> CodexAccountIdentity | None:
    """Return an opaque ChatGPT account digest without retaining paths or tokens.

    Codex also supports API-key authentication, so a missing account identifier
    is observable as ``None`` rather than being treated as an authentication
    failure. Callers that require one specific ChatGPT account must additionally
    require an explicit ``codex_home``.
    """

    if model != "codex" and not model.startswith("codex/"):
        return None
    config_dir, binding = _codex_config_dir(kwargs)
    auth_path = config_dir / "auth.json"
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CodexAccountIdentity(binding=binding, account_id_sha256=None)
    tokens = payload.get("tokens")
    account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
    if not isinstance(account_id, str) or not account_id.strip():
        return CodexAccountIdentity(binding=binding, account_id_sha256=None)
    digest = hashlib.sha256(account_id.strip().encode("utf-8")).hexdigest()
    return CodexAccountIdentity(
        binding=binding,
        account_id_sha256=f"sha256:{digest}",
    )
