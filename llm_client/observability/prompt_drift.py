"""Retrospective prompt-size drift detection over collected observability rows.

Component A of the prompt-size contract stack. This module answers a question
the existing cost surfaces cannot: *has a given task's prompt payload grown far
past its own historical norm?*

Two properties make this worth its own surface rather than a cost report:

1. **Cost hides the drift.** Prompt caching means a larger payload can bill
   less than a smaller one. Observed on real data: a 1,231,999-token call cost
   $0.0276 (617,073 tokens cached) while a 615,835-token call on the same task
   and model cost $0.3109. Ranked by cost, the worse offender looks 11x
   cheaper. Drift is therefore measured in ``prompt_tokens`` only.

2. **Absolute thresholds do not transfer.** A 200K-token prompt is normal for
   one task and a 50x regression for another. Every comparison here is against
   the task's *own* baseline.

This reads rows that are already recorded; it requires no contract to have been
declared and no call site to have been changed, so it covers call sites that
will never get a contract written for them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import llm_client.io_log as _io_log
from llm_client.core.errors import LLMObservabilityUnavailableError

DEFAULT_BASELINE_DAYS = 30
DEFAULT_RECENT_DAYS = 7
DEFAULT_MIN_CALLS = 20
DEFAULT_GROWTH_RATIO = 3.0
DEFAULT_DISPERSION_RATIO = 5.0


@dataclass(frozen=True)
class PromptDriftFinding:
    """One task whose prompt size drifted against its own history."""

    project: str | None
    task: str
    baseline_calls: int
    baseline_median_prompt_tokens: float | None
    recent_calls: int
    recent_median_prompt_tokens: float
    recent_p95_prompt_tokens: float
    recent_max_prompt_tokens: int
    growth_ratio: float | None
    dispersion_ratio: float | None
    reasons: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "task": self.task,
            "baseline_calls": self.baseline_calls,
            "baseline_median_prompt_tokens": self.baseline_median_prompt_tokens,
            "recent_calls": self.recent_calls,
            "recent_median_prompt_tokens": self.recent_median_prompt_tokens,
            "recent_p95_prompt_tokens": self.recent_p95_prompt_tokens,
            "recent_max_prompt_tokens": self.recent_max_prompt_tokens,
            "growth_ratio": self.growth_ratio,
            "dispersion_ratio": self.dispersion_ratio,
            "reasons": list(self.reasons),
        }


def _median(values: list[int]) -> float:
    if not values:
        raise ValueError("median of empty sample")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile(values: list[int], fraction: float) -> float:
    if not values:
        raise ValueError("percentile of empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _fetch_samples(
    db: sqlite3.Connection,
    *,
    since: str,
    until: str | None,
    project: str | None,
    task: str | None,
) -> dict[tuple[str | None, str], list[int]]:
    """Collect prompt_tokens per (project, task) over one time window."""

    clauses = [
        "timestamp >= ?",
        "prompt_tokens IS NOT NULL",
        "task IS NOT NULL",
        "error IS NULL",
    ]
    params: list[Any] = [since]
    if until is not None:
        clauses.append("timestamp < ?")
        params.append(until)
    if project is not None:
        clauses.append("project = ?")
        params.append(project)
    if task is not None:
        clauses.append("task = ?")
        params.append(task)

    sql = (
        "SELECT project, task, prompt_tokens FROM llm_calls WHERE "
        + " AND ".join(clauses)
    )
    samples: dict[tuple[str | None, str], list[int]] = {}
    for row_project, row_task, prompt_tokens in db.execute(sql, params):
        samples.setdefault((row_project, str(row_task)), []).append(int(prompt_tokens))
    return samples


def find_prompt_drift(
    *,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    recent_days: int = DEFAULT_RECENT_DAYS,
    min_calls: int = DEFAULT_MIN_CALLS,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    dispersion_ratio: float = DEFAULT_DISPERSION_RATIO,
    project: str | None = None,
    task: str | None = None,
    now: datetime | None = None,
) -> list[PromptDriftFinding]:
    """Find tasks whose recent prompt size drifted against their own history.

    Two independent signals are reported, because they catch different shapes
    of the same problem:

    * ``prompt_growth`` -- the recent median is ``growth_ratio`` times the
      baseline median. Catches a payload that grew and stayed grown.
    * ``prompt_dispersion`` -- within the recent window, p95 is
      ``dispersion_ratio`` times the median. Catches a task where most calls
      are normal and a subset is enormous, which a median-only comparison
      hides entirely.

    Args:
        baseline_days: Length of the historical window preceding the recent
            window, used as the task's own reference.
        recent_days: Length of the window being judged.
        min_calls: Minimum calls required in *each* window before a task is
            judged at all. Small samples produce meaningless ratios.
        growth_ratio: Recent-median / baseline-median breach threshold.
        dispersion_ratio: Recent p95 / recent median breach threshold.
        project: Restrict to one project.
        task: Restrict to one task.
        now: Injectable clock for deterministic tests.

    Returns:
        Findings ordered by severity (largest breach first).

    Raises:
        LLMObservabilityUnavailableError: If the observability database cannot
            be opened. Reporting "no drift" from an unreadable database would
            be a silent all-clear, which this substrate does not do.
    """

    if baseline_days <= 0 or recent_days <= 0:
        raise ValueError("baseline_days and recent_days must be positive")
    if min_calls < 1:
        raise ValueError("min_calls must be >= 1")
    if growth_ratio <= 1.0 or dispersion_ratio <= 1.0:
        raise ValueError("ratio thresholds must be > 1.0")

    current = now or datetime.now(timezone.utc)
    recent_start = current - timedelta(days=recent_days)
    baseline_start = recent_start - timedelta(days=baseline_days)

    try:
        db = _io_log._get_db()
    except Exception as exc:
        raise LLMObservabilityUnavailableError(
            "cannot assess prompt drift: observability database is unavailable "
            "(missing, locked, or corrupted); refusing to report 'no drift'",
            original=exc,
        ) from exc

    baseline = _fetch_samples(
        db,
        since=baseline_start.isoformat(),
        until=recent_start.isoformat(),
        project=project,
        task=task,
    )
    recent = _fetch_samples(
        db,
        since=recent_start.isoformat(),
        until=None,
        project=project,
        task=task,
    )

    findings: list[PromptDriftFinding] = []
    for key, recent_samples in recent.items():
        if len(recent_samples) < min_calls:
            continue
        recent_median = _median(recent_samples)
        recent_p95 = _percentile(recent_samples, 0.95)

        baseline_samples = baseline.get(key, [])
        baseline_median = (
            _median(baseline_samples) if len(baseline_samples) >= min_calls else None
        )

        reasons: list[str] = []
        growth: float | None = None
        if baseline_median is not None and baseline_median > 0:
            growth = recent_median / baseline_median
            if growth >= growth_ratio:
                reasons.append("prompt_growth")

        dispersion: float | None = None
        if recent_median > 0:
            dispersion = recent_p95 / recent_median
            if dispersion >= dispersion_ratio:
                reasons.append("prompt_dispersion")

        if not reasons:
            continue

        row_project, row_task = key
        findings.append(
            PromptDriftFinding(
                project=row_project,
                task=row_task,
                baseline_calls=len(baseline_samples),
                baseline_median_prompt_tokens=baseline_median,
                recent_calls=len(recent_samples),
                recent_median_prompt_tokens=recent_median,
                recent_p95_prompt_tokens=recent_p95,
                recent_max_prompt_tokens=max(recent_samples),
                growth_ratio=growth,
                dispersion_ratio=dispersion,
                reasons=tuple(reasons),
            )
        )

    findings.sort(
        key=lambda f: max(f.growth_ratio or 0.0, f.dispersion_ratio or 0.0),
        reverse=True,
    )
    return findings
