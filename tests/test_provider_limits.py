"""Both-sign tests for the OpenRouter provider-limit observer boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from llm_client.provider_limits import (
    ProviderLimitErrorCodeV1,
    ProviderLimitObservationErrorV1,
    ProviderLimitObserverConfigV1,
    _observe_openrouter_key_limit_with_transport_v1,
    inspect_openrouter_key_environment_v1,
    observe_openrouter_key_limit_v1,
)
from llm_client.utils.openrouter import (
    OPENROUTER_API_BASE_ENV,
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_API_KEYS_ENV,
)


SECRET = "sk-or-v1-plan104-super-secret"
CANONICAL_URL = "https://openrouter.ai/api/v1/key"


def _clear_openrouter_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every supported OpenRouter key source from the test environment."""
    for name in tuple(os.environ):
        if name in {
            OPENROUTER_API_KEY_ENV,
            OPENROUTER_API_KEYS_ENV,
            OPENROUTER_API_BASE_ENV,
            "LLM_CLIENT_KEYS_FILE",
        } or name.startswith(f"{OPENROUTER_API_KEY_ENV}_"):
            monkeypatch.delenv(name, raising=False)


def _valid_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Install one primary key plus an explicit empty key file."""
    _clear_openrouter_environment(monkeypatch)
    keys_file = tmp_path / "empty-keys.env"
    keys_file.write_bytes(b"")
    monkeypatch.setenv("LLM_CLIENT_KEYS_FILE", str(keys_file))
    monkeypatch.setenv(OPENROUTER_API_KEY_ENV, SECRET)
    return keys_file


def _json_response(payload: str, *, status_code: int = 200, content_type: str = "application/json") -> httpx.Response:
    """Build a raw response so numeric lexemes are not pre-coerced to floats."""
    return httpx.Response(
        status_code,
        content=payload.encode("utf-8"),
        headers={"content-type": content_type},
    )


def _valid_payload(*, limit: str = "25.00", remaining: str = "24.875") -> str:
    """Return one complete provider response with additive private fields."""
    return (
        '{"data": {'
        f'"limit": {limit}, "limit_remaining": {remaining}, '
        '"limit_reset": null, "include_byok_in_limit": true, '
        '"is_management_key": false, "is_provisioning_key": false, '
        '"expires_at": null, "label": "must-not-cross", '
        '"creator_user_id": "must-not-cross"}}'
    )


def test_inspect_openrouter_key_environment_is_source_aware_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)

    environment = inspect_openrouter_key_environment_v1()

    assert environment.key_count == 1
    assert environment.configured_sources == (OPENROUTER_API_KEY_ENV,)
    assert environment.rotation_sources_absent is True
    assert environment.llm_client_keys_file_empty is True
    assert environment.inventory_phase == "after_llm_client_import"
    assert environment.key_fingerprint.startswith("sha256:")
    rendered = environment.model_dump_json()
    assert SECRET not in rendered
    assert SECRET[-4:] not in rendered


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda monkeypatch, tmp_path: monkeypatch.delenv(OPENROUTER_API_KEY_ENV), ProviderLimitErrorCodeV1.KEY_COUNT_INVALID),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv(OPENROUTER_API_KEYS_ENV, SECRET), ProviderLimitErrorCodeV1.ROTATION_SOURCE_PRESENT),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv(f"{OPENROUTER_API_KEY_ENV}_1", SECRET), ProviderLimitErrorCodeV1.ROTATION_SOURCE_PRESENT),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv(OPENROUTER_API_KEYS_ENV, "second-secret"), ProviderLimitErrorCodeV1.ROTATION_SOURCE_PRESENT),
        (lambda monkeypatch, tmp_path: monkeypatch.delenv("LLM_CLIENT_KEYS_FILE"), ProviderLimitErrorCodeV1.KEYS_FILE_NOT_EXPLICIT),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv("LLM_CLIENT_KEYS_FILE", "relative.env"), ProviderLimitErrorCodeV1.KEYS_FILE_NOT_ABSOLUTE),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv("LLM_CLIENT_KEYS_FILE", str(tmp_path / "missing.env")), ProviderLimitErrorCodeV1.KEYS_FILE_MISSING),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv("LLM_CLIENT_KEYS_FILE", str(tmp_path)), ProviderLimitErrorCodeV1.KEYS_FILE_MISSING),
        (lambda monkeypatch, tmp_path: (tmp_path / "empty-keys.env").write_text("OPENROUTER_API_KEY=bad\n"), ProviderLimitErrorCodeV1.KEYS_FILE_NOT_EMPTY),
        (lambda monkeypatch, tmp_path: monkeypatch.setenv(OPENROUTER_API_BASE_ENV, "https://example.invalid/api/v1"), ProviderLimitErrorCodeV1.API_ORIGIN_INVALID),
    ],
)
def test_environment_ambiguity_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate: object,
    code: ProviderLimitErrorCodeV1,
) -> None:
    _valid_environment(monkeypatch, tmp_path)
    assert callable(mutate)
    mutate(monkeypatch, tmp_path)  # type: ignore[operator]

    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        inspect_openrouter_key_environment_v1()

    assert captured.value.code is code
    assert SECRET not in str(captured.value)
    assert SECRET[-4:] not in str(captured.value)


def test_symlink_key_file_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = _valid_environment(monkeypatch, tmp_path)
    link = tmp_path / "linked.env"
    link.symlink_to(target)
    monkeypatch.setenv("LLM_CLIENT_KEYS_FILE", str(link))

    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        inspect_openrouter_key_environment_v1()

    assert captured.value.code is ProviderLimitErrorCodeV1.KEYS_FILE_SYMLINK


def test_exact_decimal_and_provider_state_survive_strict_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)
    exact = "0.1234567890123456789"

    # mock-ok: the external provider transport is controlled; parsing, identity,
    # environment reinspection, and the public models are real.
    transport = httpx.MockTransport(lambda request: _json_response(_valid_payload(limit=exact)))
    preflight = _observe_openrouter_key_limit_with_transport_v1(
        allow_provider_read=True,
        transport=transport,
        observed_at=datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc),
    )

    assert preflight.observation.limit_usd == Decimal(exact)
    assert preflight.observation.limit_remaining_usd == Decimal("24.875")
    assert preflight.observation.limit_reset is None
    assert preflight.observation.include_byok_in_limit is True
    assert preflight.observation.is_management_key is False
    assert preflight.observation.is_provisioning_key is False
    assert preflight.observation.expires_at is None
    assert preflight.observation.provider_limit_state_observed is True
    assert preflight.observation.evidence_kind == "authenticated_provider_read"
    assert preflight.observation.strict_invoice_ceiling_supported is False
    rendered = preflight.model_dump_json()
    assert "must-not-cross" not in rendered
    assert SECRET not in rendered
    assert SECRET[-4:] not in rendered


def test_unlimited_and_expiring_management_state_is_reported_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)
    payload = (
        '{"data":{"limit":null,"limit_remaining":null,"limit_reset":"monthly",'
        '"include_byok_in_limit":false,"is_management_key":true,'
        '"is_provisioning_key":true,"expires_at":"2026-08-01T00:00:00Z"}}'
    )
    # mock-ok: provider state is controlled while the observation contract is real.
    transport = httpx.MockTransport(lambda request: _json_response(payload))

    preflight = _observe_openrouter_key_limit_with_transport_v1(
        allow_provider_read=True,
        transport=transport,
    )

    assert preflight.observation.limit_usd is None
    assert preflight.observation.limit_remaining_usd is None
    assert preflight.observation.limit_reset == "monthly"
    assert preflight.observation.include_byok_in_limit is False
    assert preflight.observation.is_management_key is True
    assert preflight.observation.is_provisioning_key is True
    assert preflight.observation.expires_at == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_provider_read_requires_explicit_authority_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)

    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        observe_openrouter_key_limit_v1(allow_provider_read=False)

    assert captured.value.code is ProviderLimitErrorCodeV1.PROVIDER_READ_NOT_AUTHORIZED


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_json_response("{}", status_code=401), ProviderLimitErrorCodeV1.PROVIDER_HTTP_STATUS),
        (_json_response("{}", status_code=302), ProviderLimitErrorCodeV1.PROVIDER_REDIRECT),
        (_json_response("{}", content_type="text/plain"), ProviderLimitErrorCodeV1.PROVIDER_CONTENT_TYPE),
        (_json_response("not json"), ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_INVALID),
        (httpx.Response(200, content=b"\xff", headers={"content-type": "application/json"}), ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_INVALID),
        (_json_response("{}"), ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_INVALID),
        (_json_response(_valid_payload(limit="-1")), ProviderLimitErrorCodeV1.PROVIDER_VALUE_INVALID),
        (_json_response(_valid_payload(limit="NaN")), ProviderLimitErrorCodeV1.PROVIDER_VALUE_INVALID),
    ],
)
def test_provider_response_failures_are_typed_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response: httpx.Response,
    code: ProviderLimitErrorCodeV1,
) -> None:
    _valid_environment(monkeypatch, tmp_path)
    # mock-ok: transport failure variants are controlled; the observer boundary is real.
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        _observe_openrouter_key_limit_with_transport_v1(
            allow_provider_read=True,
            transport=transport,
        )

    assert captured.value.code is code
    rendered = json.dumps(captured.value.as_dict(), sort_keys=True)
    assert SECRET not in rendered
    assert SECRET[-4:] not in rendered
    assert "must-not-cross" not in rendered


def test_provider_response_is_streamed_under_the_configured_size_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)
    response = _json_response(_valid_payload())
    # mock-ok: a controlled response proves the real reader stops at its byte cap.
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        _observe_openrouter_key_limit_with_transport_v1(
            allow_provider_read=True,
            config=ProviderLimitObserverConfigV1(max_response_bytes=16),
            transport=transport,
        )

    assert captured.value.code is ProviderLimitErrorCodeV1.PROVIDER_PAYLOAD_TOO_LARGE


def test_provider_transport_failure_is_typed_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("controlled failure", request=request)

    # mock-ok: the transport raises a real httpx failure at the external seam.
    transport = httpx.MockTransport(fail)
    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        _observe_openrouter_key_limit_with_transport_v1(
            allow_provider_read=True,
            transport=transport,
        )

    assert captured.value.code is ProviderLimitErrorCodeV1.PROVIDER_TRANSPORT
    assert SECRET not in str(captured.value)


def test_environment_substitution_during_read_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _valid_environment(monkeypatch, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "replacement-secret")
        return _json_response(_valid_payload())

    # mock-ok: handler mutates the real process environment at the transport seam.
    transport = httpx.MockTransport(handler)
    with pytest.raises(ProviderLimitObservationErrorV1) as captured:
        _observe_openrouter_key_limit_with_transport_v1(
            allow_provider_read=True,
            transport=transport,
        )

    assert captured.value.code is ProviderLimitErrorCodeV1.ENVIRONMENT_CHANGED


def test_poisoned_default_key_file_cannot_repopulate_explicit_empty_child(tmp_path: Path) -> None:
    home = tmp_path / "home"
    secrets_dir = home / ".secrets"
    secrets_dir.mkdir(parents=True)
    poisoned = "sk-or-v1-poisoned-default"
    (secrets_dir / "api_keys.env").write_text(
        f"OPENROUTER_API_KEY={poisoned}\n",
        encoding="utf-8",
    )
    empty = tmp_path / "empty.env"
    empty.write_bytes(b"")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["LLM_CLIENT_KEYS_FILE"] = str(empty)
    env.pop(OPENROUTER_API_KEY_ENV, None)
    env.pop(OPENROUTER_API_KEYS_ENV, None)
    for name in tuple(env):
        if name.startswith(f"{OPENROUTER_API_KEY_ENV}_"):
            env.pop(name)

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; import llm_client; "
                "print('loaded=' + str(os.environ.get('OPENROUTER_API_KEY'))); "
                "from llm_client.provider_limits import inspect_openrouter_key_environment_v1; "
                "inspect_openrouter_key_environment_v1()"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "loaded=None" in proc.stdout
    assert poisoned not in proc.stdout
    assert poisoned not in proc.stderr


@pytest.mark.integration
def test_live_current_key_read_returns_strict_secret_free_envelope() -> None:
    """Exercise the real provider read only behind two explicit integration gates."""
    if os.environ.get("LLM_CLIENT_INTEGRATION") != "1":
        pytest.skip("Set LLM_CLIENT_INTEGRATION=1 to enable integration tests.")
    if os.environ.get("LLM_CLIENT_PROVIDER_LIMIT_READ") != "1":
        pytest.skip("Set LLM_CLIENT_PROVIDER_LIMIT_READ=1 to authorize this provider read.")

    result = observe_openrouter_key_limit_v1(allow_provider_read=True)
    rendered = result.model_dump_json()

    assert result.observation.provider_limit_state_observed is True
    assert result.observation.evidence_kind == "authenticated_provider_read"
    assert result.observation.strict_invoice_ceiling_supported is False
    assert os.environ[OPENROUTER_API_KEY_ENV] not in rendered
