"""Bounded asynchronous execution for the dedicated Codex subscription lane."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_client.core.client import acall_llm
from llm_client.core.model_selection import (
    ResolvedWorkloadRoute,
    WorkloadRouteContext,
    resolve_workload_route,
)
from llm_client.observability import ObservedRun


class CodexCanaryConfig(BaseModel):
    """Hard limits for one dedicated account lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: str = Field(min_length=1)
    queue_size: int = Field(default=8, ge=1, le=100)
    worker_count: Literal[1] = 1
    hard_timeout_s: float = Field(default=300.0, gt=0, le=3600)
    max_retries: int = Field(default=0, ge=0, le=2)
    max_jobs: int | None = Field(default=None, ge=1)
    fallback_model: str | None = None
    fallback_provider: Literal["openai_api", "openrouter"] | None = None
    fallback_spend_ceiling_usd: float = Field(default=0.0, ge=0, le=100.0)
    receipt_path: Path

    @model_validator(mode="after")
    def _validate_fallback_contract(self) -> CodexCanaryConfig:
        self.validate_fallback()
        return self

    def validate_fallback(self) -> None:
        if (self.fallback_model is None) != (self.fallback_provider is None):
            raise ValueError("fallback_model and fallback_provider must be configured together")
        if self.fallback_model is not None and self.fallback_spend_ceiling_usd <= 0:
            raise ValueError("fallback_spend_ceiling_usd must be positive when fallback is configured")
        if self.fallback_model is None and self.fallback_spend_ceiling_usd != 0:
            raise ValueError("fallback spend ceiling without an explicit fallback is invalid")


class CodexCanaryJob(BaseModel):
    """A caller-supplied async job with no implicit model selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    task: str = Field(min_length=1)
    trace_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    messages: list[dict[str, Any]] = Field(min_length=1)
    max_budget: float = Field(default=0.01, gt=0)
    reasoning_effort: Literal["medium"] = "medium"


class CodexCanaryReceipt(BaseModel):
    """Durable queue-level receipt for one submitted canary job."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["codex_canary_receipt_v1"] = "codex_canary_receipt_v1"
    job_id: str
    account_id: str
    task: str
    trace_id: str
    route: str
    model: str
    status: Literal["succeeded", "failed", "cancelled", "rejected"]
    started_at: datetime
    completed_at: datetime
    latency_s: float = Field(ge=0)
    retries: int = Field(ge=0)
    fallback_used: bool = False
    fallback_tag: str | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CanaryTelemetry:
    submitted: int
    succeeded: int
    failed: int
    cancelled: int
    rejected: int
    fallback_used: int
    total_latency_s: float
    observed_cost_usd: float


@dataclass
class _QueuedJob:
    job_id: str
    job: CodexCanaryJob
    future: asyncio.Future[CodexCanaryReceipt]


class CodexCanaryQueue:
    """One-account, one-worker bounded queue for trusted async work."""

    def __init__(self, config: CodexCanaryConfig, *, route: ResolvedWorkloadRoute) -> None:
        config.validate_fallback()
        if route.provider != "codex_subscription" or route.model != "codex/gpt-5.6-luna":
            raise ValueError("CodexCanaryQueue requires the explicit codex_subscription Luna route")
        self.config = config
        self.route = route
        self._queue: asyncio.Queue[_QueuedJob | None] = asyncio.Queue(maxsize=config.queue_size)
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._accepted = 0
        self._telemetry = Counter[str]()
        self._total_latency_s = 0.0
        self._observed_cost_usd = 0.0

    @classmethod
    def for_trusted_async_work(cls, config: CodexCanaryConfig) -> CodexCanaryQueue:
        route = resolve_workload_route(
            WorkloadRouteContext(
                codex_compatible=True,
                environment="trusted_private_automation",
                subscription_auth_supported=True,
                subscription_capacity="available",
                requires_openai_api_contract=False,
                requires_openrouter_features=False,
                openrouter_is_live_best_value=False,
            )
        )
        return cls(config, route=route)

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("canary queue is closed")
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name=f"codex-canary-{self.config.account_id}")

    async def submit(self, job: CodexCanaryJob) -> CodexCanaryReceipt:
        await self.start()
        if self._closed:
            raise RuntimeError("canary queue is closed")
        if self.config.max_jobs is not None and self._accepted >= self.config.max_jobs:
            return await self._reject(job, "job quota exhausted")
        self._accepted += 1
        future: asyncio.Future[CodexCanaryReceipt] = asyncio.get_running_loop().create_future()
        await self._queue.put(_QueuedJob(uuid4().hex, job, future))
        return await future

    async def close(self) -> None:
        self._closed = True
        if self._worker is not None:
            await self._queue.put(None)
            await self._worker
            self._worker = None

    def telemetry(self) -> CanaryTelemetry:
        return CanaryTelemetry(
            submitted=self._accepted,
            succeeded=self._telemetry["succeeded"],
            failed=self._telemetry["failed"],
            cancelled=self._telemetry["cancelled"],
            rejected=self._telemetry["rejected"],
            fallback_used=self._telemetry["fallback_used"],
            total_latency_s=self._total_latency_s,
            observed_cost_usd=self._observed_cost_usd,
        )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                receipt = await self._execute(item)
                if not item.future.done():
                    item.future.set_result(receipt)
            except Exception as exc:  # noqa: BLE001 - terminal receipt boundary
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def _execute(self, item: _QueuedJob) -> CodexCanaryReceipt:
        started = datetime.now(timezone.utc)
        began = time.monotonic()
        fallback_used = False
        fallback_tag: str | None = None
        cost_usd: float | None = None
        error: BaseException | None = None
        result: Any = None
        try:
            async with ObservedRun(
                project="llm_client",
                operation="codex_canary_job",
                executable="llm_client.codex_canary.CodexCanaryQueue",
                run_id=f"codex-canary-{item.job_id}",
                root_trace_id=item.job.trace_id,
                requested_model=self.route.model,
                reasoning_effort=item.job.reasoning_effort,
                max_budget=item.job.max_budget,
            ) as run:
                run.set_phase("codex_subscription_call")
                try:
                    result = await asyncio.wait_for(
                        acall_llm(
                            self.route.model,
                            item.job.messages,
                            timeout=int(self.config.hard_timeout_s),
                            num_retries=self.config.max_retries,
                            reasoning_effort=item.job.reasoning_effort,
                            task=item.job.task,
                            trace_id=run.child_trace_id("codex_subscription"),
                            max_budget=item.job.max_budget,
                            model_justification=self.route.model_justification,
                        ),
                        timeout=self.config.hard_timeout_s,
                    )
                except Exception as primary_error:
                    if self.config.fallback_model is None:
                        raise
                    fallback_used = True
                    fallback_tag = f"explicit_fallback:{self.config.fallback_provider}"
                    run.set_phase("explicit_paid_fallback")
                    result = await asyncio.wait_for(
                        acall_llm(
                            self.config.fallback_model,
                            item.job.messages,
                            timeout=int(self.config.hard_timeout_s),
                            num_retries=0,
                            reasoning_effort=item.job.reasoning_effort,
                            task=item.job.task,
                            trace_id=run.child_trace_id("explicit_paid_fallback"),
                            max_budget=min(item.job.max_budget, self.config.fallback_spend_ceiling_usd),
                            model_justification=(
                                f"Explicit canary fallback after Codex failure; provider="
                                f"{self.config.fallback_provider}; spend ceiling="
                                f"{self.config.fallback_spend_ceiling_usd:.2f} USD"
                            ),
                        ),
                        timeout=self.config.hard_timeout_s,
                    )
                    if result is None:
                        raise RuntimeError("explicit fallback returned no result") from primary_error
                cost_usd = _result_cost(result)
                if fallback_used and cost_usd is not None and cost_usd > self.config.fallback_spend_ceiling_usd:
                    raise RuntimeError("observed fallback cost exceeded the configured spend ceiling")
        except asyncio.CancelledError as exc:
            error = exc
            status: Literal["succeeded", "failed", "cancelled"] = "cancelled"
        except Exception as exc:  # noqa: BLE001 - durable terminal evidence
            error = exc
            status = "failed"
        else:
            status = "succeeded"
        latency = time.monotonic() - began
        self._telemetry[status] += 1
        self._telemetry["fallback_used"] += int(fallback_used)
        self._total_latency_s += latency
        self._observed_cost_usd += cost_usd or 0.0
        receipt = CodexCanaryReceipt(
            job_id=item.job_id,
            account_id=self.config.account_id,
            task=item.job.task,
            trace_id=item.job.trace_id,
            route="codex_subscription_async",
            model=self.route.model,
            status=status,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            latency_s=latency,
            retries=self.config.max_retries,
            fallback_used=fallback_used,
            fallback_tag=fallback_tag,
            cost_usd=cost_usd,
            error_type=type(error).__name__ if error else None,
            error_message=str(error)[:500] if error else None,
        )
        _append_receipt(self.config.receipt_path, receipt)
        return receipt

    async def _reject(self, job: CodexCanaryJob, reason: str) -> CodexCanaryReceipt:
        now = datetime.now(timezone.utc)
        receipt = CodexCanaryReceipt(
            job_id=uuid4().hex,
            account_id=self.config.account_id,
            task=job.task,
            trace_id=job.trace_id,
            route="codex_subscription_async",
            model=self.route.model,
            status="rejected",
            started_at=now,
            completed_at=now,
            latency_s=0,
            retries=0,
            error_type="QuotaExceeded",
            error_message=reason,
        )
        self._telemetry["rejected"] += 1
        _append_receipt(self.config.receipt_path, receipt)
        return receipt


def _result_cost(result: Any) -> float | None:
    value = getattr(result, "cost", None)
    return float(value) if value is not None else None


def _append_receipt(path: Path, receipt: CodexCanaryReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt.model_dump(mode="json"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


__all__ = ["CanaryTelemetry", "CodexCanaryConfig", "CodexCanaryJob", "CodexCanaryQueue", "CodexCanaryReceipt"]
