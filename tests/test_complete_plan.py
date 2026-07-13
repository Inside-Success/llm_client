"""Contract tests for the mandatory plan-completion harness."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from scripts.meta import complete_plan as completion


def test_positive_seconds_rejects_invalid_timeout_values() -> None:
    """The agent-facing timeout control fails loud on unusable values."""

    assert completion._positive_seconds("901") == 901
    with pytest.raises(argparse.ArgumentTypeError, match="whole number"):
        completion._positive_seconds("later")
    with pytest.raises(argparse.ArgumentTypeError, match="greater than zero"):
        completion._positive_seconds("0")


def test_unit_timeout_reports_recent_captured_progress(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A timed-out suite names its last captured test instead of returning opaque failure."""

    def raise_timeout(*_args: object, **kwargs: object) -> None:
        assert kwargs["timeout"] == 17
        raise subprocess.TimeoutExpired(
            cmd="pytest",
            timeout=17,
            output=b"tests/test_example.py::test_last_started PASSED\n",
            stderr=b"still running\n",
        )

    monkeypatch.setattr(completion.subprocess, "run", raise_timeout)
    passed, summary = completion.run_unit_tests(
        tmp_path,
        timeout_seconds=17,
    )

    assert passed is False
    assert summary == "timeout after 17s"
    output = capsys.readouterr().out
    assert "test_last_started" in output
    assert "still running" in output


def test_main_threads_explicit_timeout_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI timeout reaches the completion orchestrator as a typed integer."""

    captured: dict[str, object] = {}

    def fake_complete_plan(**kwargs: object) -> bool:
        captured.update(kwargs)
        return True

    monkeypatch.setattr(completion, "complete_plan", fake_complete_plan)
    monkeypatch.setattr(
        completion.sys,
        "argv",
        ["complete_plan.py", "--plan", "99", "--test-timeout-seconds", "1234"],
    )

    assert completion.main() == 0
    assert captured["test_timeout_seconds"] == 1234
