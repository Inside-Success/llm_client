"""Tests for the prompt-size contract stack.

Covers all three components:

* ``check_prompt_size`` -- the call-boundary ceiling (Component B)
* ``prompt_context_contract`` -- per-variable budgets at render time (Component C)
* ``find_prompt_drift`` -- retrospective drift detection (Component A)

The behaviour these tests pin down is the one the mechanism exists for: a
payload that is *permitted by name* but has grown far past its budget must be
caught and attributed. A name-only allowlist did not catch that, which is why
every contract here is budget-bearing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_client.core.errors import LLMPromptBudgetExceededError
from llm_client.execution.call_contracts import (
    _TASK_PROMPT_BUDGETS,
    check_prompt_size,
    estimate_prompt_tokens,
    get_task_prompt_budget,
    register_task_prompt_budget,
)
from llm_client.prompt_context_contract import (
    PromptContextContractError,
    contract_path_for,
    enforce_contract,
    load_contract,
)


@pytest.fixture(autouse=True)
def _clear_registered_budgets():
    """Task budgets are process-global; keep tests independent."""
    saved = dict(_TASK_PROMPT_BUDGETS)
    _TASK_PROMPT_BUDGETS.clear()
    yield
    _TASK_PROMPT_BUDGETS.clear()
    _TASK_PROMPT_BUDGETS.update(saved)


# --------------------------------------------------------------------------
# Component B: call-boundary ceiling
# --------------------------------------------------------------------------


def test_registered_budget_is_readable() -> None:
    register_task_prompt_budget("demo.task", 1000)
    assert get_task_prompt_budget("demo.task") == 1000
    assert get_task_prompt_budget("unregistered.task") is None


def test_reregistering_same_value_is_idempotent() -> None:
    register_task_prompt_budget("demo.task", 1000)
    register_task_prompt_budget("demo.task", 1000)
    assert get_task_prompt_budget("demo.task") == 1000


def test_conflicting_registration_fails_loud() -> None:
    """Two modules must not silently disagree about one task's ceiling."""
    register_task_prompt_budget("demo.task", 1000)
    with pytest.raises(ValueError, match="conflicting prompt budget"):
        register_task_prompt_budget("demo.task", 2000)


def test_under_budget_returns_measurement_without_raising() -> None:
    register_task_prompt_budget("demo.task", 1000)
    estimated = check_prompt_size("demo.task", "x" * 400)
    assert estimated == 100


def test_no_ceiling_still_measures() -> None:
    """Measurement is unconditional; only enforcement is opt-in."""
    assert check_prompt_size("unregistered.task", "x" * 4000) == 1000


def test_over_budget_warns_by_default(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """Warn-by-default keeps a cost problem from becoming an availability problem."""
    monkeypatch.delenv("LLM_CLIENT_PROMPT_SIZE_STRICT", raising=False)
    monkeypatch.delenv("CI", raising=False)
    register_task_prompt_budget("demo.task", 100)
    warnings: list[str] = []

    with caplog.at_level("WARNING"):
        estimated = check_prompt_size("demo.task", "x" * 40_000, warning_sink=warnings)

    assert estimated == 10_000
    assert warnings and "PROMPT_SIZE" in warnings[0]
    assert "not truncated" in caplog.text


def test_over_budget_raises_in_strict_mode(monkeypatch) -> None:
    monkeypatch.setenv("LLM_CLIENT_PROMPT_SIZE_STRICT", "1")
    register_task_prompt_budget("demo.task", 100)

    with pytest.raises(LLMPromptBudgetExceededError, match=r"100\.0x"):
        check_prompt_size("demo.task", "x" * 40_000)


def test_explicit_argument_overrides_registered_budget(monkeypatch) -> None:
    monkeypatch.setenv("LLM_CLIENT_PROMPT_SIZE_STRICT", "1")
    register_task_prompt_budget("demo.task", 100)

    # Explicit per-call ceiling wins over the registered default.
    assert check_prompt_size("demo.task", "x" * 40_000, max_prompt_tokens=20_000) == 10_000


def test_estimate_is_chars_over_four() -> None:
    assert estimate_prompt_tokens("x" * 4000) == 1000


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_budget_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        register_task_prompt_budget("demo.task", bad)


def test_boolean_budget_rejected() -> None:
    """bool is an int subclass; a True ceiling is a bug, not a budget."""
    with pytest.raises(TypeError):
        register_task_prompt_budget("demo.task", True)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Component C: per-variable render-time contract
# --------------------------------------------------------------------------


def _write_contract(tmp_path: Path, body: str) -> Path:
    template = tmp_path / "demo.yaml"
    template.write_text("messages:\n  - role: user\n    content: hi\n", encoding="utf-8")
    contract_path_for(template).write_text(body, encoding="utf-8")
    return template


def test_contract_path_is_a_sibling_of_the_template(tmp_path: Path) -> None:
    assert contract_path_for(tmp_path / "foo.yaml").name == "foo.contract.yaml"


def test_absent_contract_is_not_an_error(tmp_path: Path) -> None:
    template = tmp_path / "demo.yaml"
    template.write_text("messages: []\n", encoding="utf-8")
    assert load_contract(template) is None
    assert enforce_contract(template, {"anything": "x" * 10_000}, strict=True) == []


def test_oversized_variable_is_named(tmp_path: Path) -> None:
    """Attribution is the deliverable: the breach must name the variable."""
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 100\n',
    )

    with pytest.raises(PromptContextContractError, match="artifacts_json"):
        enforce_contract(template, {"artifacts_json": "x" * 1000}, strict=True)


def test_permitted_but_oversized_variable_is_still_caught(tmp_path: Path) -> None:
    """The regression this mechanism exists for.

    The offending artifact in the reference case was *on* the call site's
    allowlist. Being declared is not enough; the budget is what catches it.
    """
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 200000\n',
    )

    breaches = enforce_contract(template, {"artifacts_json": "x" * 2_917_684}, strict=False)
    assert len(breaches) == 1
    assert "artifacts_json" in breaches[0]
    assert "14.6x" in breaches[0]


def test_all_breaches_reported_worst_first(tmp_path: Path) -> None:
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\n'
        "variables:\n"
        "  small_json:\n    max_bytes: 100\n"
        "  big_json:\n    max_bytes: 100\n",
    )

    breaches = enforce_contract(
        template, {"small_json": "x" * 200, "big_json": "x" * 5000}, strict=False
    )
    assert len(breaches) == 2
    assert "big_json" in breaches[0], "worst breach must sort first"
    assert "small_json" in breaches[1]


def test_undeclared_variable_rejected_by_default(tmp_path: Path) -> None:
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\nvariables:\n  known_json:\n    max_bytes: 100\n',
    )

    with pytest.raises(PromptContextContractError, match="not declared"):
        enforce_contract(template, {"known_json": "x", "surprise": "y"}, strict=True)


def test_undeclared_variable_allowed_when_opted_in(tmp_path: Path) -> None:
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\n'
        "allow_undeclared: true\n"
        "variables:\n  known_json:\n    max_bytes: 100\n",
    )

    assert enforce_contract(template, {"known_json": "x", "surprise": "y"}, strict=True) == []


def test_compliant_context_passes(tmp_path: Path) -> None:
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 1000\n',
    )
    assert enforce_contract(template, {"artifacts_json": "x" * 500}, strict=True) == []


def test_malformed_contract_fails_loud_rather_than_degrading(tmp_path: Path) -> None:
    """An unparseable contract must not silently mean 'no constraints'."""
    template = _write_contract(tmp_path, "schema_version: \"1.0\"\nvariables: [not, a, mapping]\n")

    with pytest.raises(PromptContextContractError, match="must be a mapping"):
        load_contract(template)


def test_unsupported_schema_version_rejected(tmp_path: Path) -> None:
    template = _write_contract(tmp_path, 'schema_version: "9.9"\nvariables: {}\n')

    with pytest.raises(PromptContextContractError, match="unsupported schema_version"):
        load_contract(template)


def test_variable_without_positive_max_bytes_rejected(tmp_path: Path) -> None:
    template = _write_contract(
        tmp_path, 'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 0\n'
    )

    with pytest.raises(PromptContextContractError, match="positive integer max_bytes"):
        load_contract(template)


def test_multibyte_values_measured_in_bytes(tmp_path: Path) -> None:
    """Budgets are byte budgets; a 2-byte character counts as two."""
    template = _write_contract(
        tmp_path,
        'schema_version: "1.0"\nvariables:\n  text:\n    max_bytes: 150\n',
    )

    breaches = enforce_contract(template, {"text": "é" * 100}, strict=False)
    assert breaches and "200 bytes" in breaches[0]


def test_render_prompt_enforces_the_contract(tmp_path: Path, monkeypatch) -> None:
    """The contract is wired into the real render path, not just callable."""
    from llm_client.prompts import render_prompt

    monkeypatch.setenv("LLM_CLIENT_PROMPT_CONTEXT_STRICT", "1")
    template = tmp_path / "demo.yaml"
    template.write_text(
        "messages:\n  - role: user\n    content: |\n      {{ artifacts_json }}\n",
        encoding="utf-8",
    )
    contract_path_for(template).write_text(
        'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 100\n',
        encoding="utf-8",
    )

    with pytest.raises(PromptContextContractError, match="artifacts_json"):
        render_prompt(template, artifacts_json="x" * 5000)


def test_render_prompt_warns_but_proceeds_by_default(tmp_path: Path, monkeypatch) -> None:
    from llm_client.prompts import render_prompt

    monkeypatch.delenv("LLM_CLIENT_PROMPT_CONTEXT_STRICT", raising=False)
    monkeypatch.delenv("CI", raising=False)
    template = tmp_path / "demo.yaml"
    template.write_text(
        "messages:\n  - role: user\n    content: |\n      {{ artifacts_json }}\n",
        encoding="utf-8",
    )
    contract_path_for(template).write_text(
        'schema_version: "1.0"\nvariables:\n  artifacts_json:\n    max_bytes: 100\n',
        encoding="utf-8",
    )

    messages = render_prompt(template, artifacts_json="x" * 5000)
    assert len(messages[0]["content"]) == 5000


# --------------------------------------------------------------------------
# Component A: retrospective drift detection
# --------------------------------------------------------------------------


def _seed_calls(conn, rows) -> None:
    conn.executemany(
        "INSERT INTO llm_calls (timestamp, project, model, task, prompt_tokens, error) "
        "VALUES (?, ?, 'test-model', ?, ?, NULL)",
        rows,
    )
    conn.commit()


@pytest.fixture
def drift_db(tmp_path, monkeypatch):
    """An isolated observability DB so drift tests never read real spend data."""
    import sqlite3

    from llm_client.observability import prompt_drift

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE llm_calls (timestamp TEXT, project TEXT, model TEXT, "
        "task TEXT, prompt_tokens INTEGER, error TEXT)"
    )
    monkeypatch.setattr(prompt_drift._io_log, "_get_db", lambda: conn)
    return conn


def _at(day: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()


def test_growth_against_own_baseline_is_detected(drift_db) -> None:
    from datetime import datetime, timezone

    from llm_client.observability.prompt_drift import find_prompt_drift

    # 30 baseline calls at ~1,000 tokens, then 30 recent calls at ~10,000.
    _seed_calls(drift_db, [(_at(20), "proj", "t.grew", 1000) for _ in range(30)])
    _seed_calls(drift_db, [(_at(40), "proj", "t.grew", 10_000) for _ in range(30)])

    findings = find_prompt_drift(
        baseline_days=30,
        recent_days=7,
        min_calls=20,
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert [f.task for f in findings] == ["t.grew"]
    assert findings[0].growth_ratio == pytest.approx(10.0)
    assert "prompt_growth" in findings[0].reasons


def test_stable_task_is_not_flagged(drift_db) -> None:
    from datetime import datetime, timezone

    from llm_client.observability.prompt_drift import find_prompt_drift

    _seed_calls(drift_db, [(_at(20), "proj", "t.stable", 1000) for _ in range(30)])
    _seed_calls(drift_db, [(_at(40), "proj", "t.stable", 1100) for _ in range(30)])

    assert (
        find_prompt_drift(
            baseline_days=30,
            recent_days=7,
            min_calls=20,
            now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        == []
    )


def test_bimodal_task_is_caught_by_dispersion(drift_db) -> None:
    """The shape a median-only comparison hides.

    Observed on real data: one task, one day, most calls ~24K prompt tokens and
    a subset over 1.2M. The median barely moves, so only dispersion catches it.
    """
    from datetime import datetime, timezone

    from llm_client.observability.prompt_drift import find_prompt_drift

    _seed_calls(drift_db, [(_at(40), "proj", "t.bimodal", 24_000) for _ in range(90)])
    _seed_calls(drift_db, [(_at(40), "proj", "t.bimodal", 1_200_000) for _ in range(10)])

    findings = find_prompt_drift(
        baseline_days=30,
        recent_days=7,
        min_calls=20,
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert [f.task for f in findings] == ["t.bimodal"]
    assert "prompt_dispersion" in findings[0].reasons
    assert findings[0].recent_max_prompt_tokens == 1_200_000
    assert findings[0].baseline_median_prompt_tokens is None


def test_small_samples_are_not_judged(drift_db) -> None:
    from datetime import datetime, timezone

    from llm_client.observability.prompt_drift import find_prompt_drift

    _seed_calls(drift_db, [(_at(20), "proj", "t.tiny", 1000) for _ in range(3)])
    _seed_calls(drift_db, [(_at(40), "proj", "t.tiny", 100_000) for _ in range(3)])

    assert (
        find_prompt_drift(
            baseline_days=30,
            recent_days=7,
            min_calls=20,
            now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        == []
    )


def test_unavailable_database_refuses_to_report_no_drift(monkeypatch) -> None:
    """An unreadable DB must not look like a clean bill of health."""
    from llm_client.core.errors import LLMObservabilityUnavailableError
    from llm_client.observability import prompt_drift

    def _boom():
        raise sqlite3.DatabaseError("database disk image is malformed")

    import sqlite3

    monkeypatch.setattr(prompt_drift._io_log, "_get_db", _boom)

    with pytest.raises(LLMObservabilityUnavailableError):
        prompt_drift.find_prompt_drift()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"baseline_days": 0},
        {"recent_days": 0},
        {"min_calls": 0},
        {"growth_ratio": 1.0},
        {"dispersion_ratio": 0.5},
    ],
)
def test_invalid_thresholds_rejected(kwargs) -> None:
    from llm_client.observability.prompt_drift import find_prompt_drift

    with pytest.raises(ValueError):
        find_prompt_drift(**kwargs)


# --------------------------------------------------------------------------
# Envelope wiring
# --------------------------------------------------------------------------


def test_max_prompt_tokens_is_a_client_control_field() -> None:
    """It must be consumed here and never forwarded to the provider."""
    from llm_client.execution.call_wrappers import _prepare_public_call_envelope

    envelope = _prepare_public_call_envelope(
        caller="call_llm",
        timeout=60,
        kwargs={
            "task": "probe.task",
            "trace_id": "probe/control-field",
            "max_budget": 0.0,
            "max_prompt_tokens": 50_000,
            "temperature": 0.1,
        },
        messages=[{"role": "user", "content": "hello"}],
    )

    assert "max_prompt_tokens" not in envelope.runtime_kwargs
    assert envelope.runtime_kwargs["temperature"] == 0.1
    assert envelope.estimated_prompt_tokens > 0


def test_envelope_measures_prompt_and_enforces_registered_ceiling(monkeypatch) -> None:
    """The ceiling is applied on the real call path, not only when called directly."""
    from llm_client.execution.call_wrappers import _prepare_public_call_envelope

    monkeypatch.setenv("LLM_CLIENT_PROMPT_SIZE_STRICT", "1")
    register_task_prompt_budget("probe.enforced", 10)

    with pytest.raises(LLMPromptBudgetExceededError):
        _prepare_public_call_envelope(
            caller="call_llm",
            timeout=60,
            kwargs={
                "task": "probe.enforced",
                "trace_id": "probe/enforced",
                "max_budget": 0.0,
            },
            messages=[{"role": "user", "content": "x" * 10_000}],
        )
