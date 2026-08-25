"""Focused contract tests for the bounded dedicated-Codex canary."""

from types import SimpleNamespace

import pytest

from llm_client.codex_canary import (
    CodexCanaryConfig,
    CodexCanaryJob,
    CodexCanaryQueue,
)


class _FakeRun:
    def __init__(self, **kwargs):
        self.root_trace_id = kwargs["root_trace_id"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def set_phase(self, phase):
        self.phase = phase

    def child_trace_id(self, segment):
        return f"{self.root_trace_id}/{segment}"


def _config(tmp_path, **overrides):
    values = {"account_id": "dedicated-1", "receipt_path": tmp_path / "receipts.jsonl"}
    values.update(overrides)
    return CodexCanaryConfig(**values)


def _job(trace="canary-test"):
    return CodexCanaryJob(
        task="canary.echo",
        trace_id=trace,
        messages=[{"role": "user", "content": "Reply with ok"}],
    )


def test_route_is_explicit_and_worker_count_is_one(tmp_path):
    queue = CodexCanaryQueue.for_trusted_async_work(_config(tmp_path))
    assert queue.route.provider == "codex_subscription"
    assert queue.route.model == "codex/gpt-5.6-luna"
    assert queue.config.worker_count == 1


def test_fallback_requires_explicit_provider_and_spend_ceiling(tmp_path):
    with pytest.raises(ValueError, match="configured together"):
        _config(tmp_path, fallback_model="gpt-5.6")
    with pytest.raises(ValueError, match="positive"):
        _config(tmp_path, fallback_model="gpt-5.6", fallback_provider="openai_api")


@pytest.mark.asyncio
async def test_queue_writes_terminal_receipt_and_telemetry(monkeypatch, tmp_path):
    monkeypatch.setattr("llm_client.codex_canary.ObservedRun", _FakeRun)

    async def fake_call(model, messages, **kwargs):
        assert model == "codex/gpt-5.6-luna"
        assert kwargs["trace_id"].endswith("/codex_subscription")
        return SimpleNamespace(cost=0.0)

    monkeypatch.setattr("llm_client.codex_canary.acall_llm", fake_call)
    queue = CodexCanaryQueue.for_trusted_async_work(_config(tmp_path))
    receipt = await queue.submit(_job())
    await queue.close()

    assert receipt.status == "succeeded"
    assert receipt.route == "codex_subscription_async"
    assert receipt.fallback_used is False
    assert queue.telemetry().succeeded == 1
    assert len((tmp_path / "receipts.jsonl").read_text().splitlines()) == 1


@pytest.mark.asyncio
async def test_fallback_is_tagged_and_uses_declared_ceiling(monkeypatch, tmp_path):
    monkeypatch.setattr("llm_client.codex_canary.ObservedRun", _FakeRun)
    models = []

    async def fake_call(model, messages, **kwargs):
        models.append(model)
        if len(models) == 1:
            raise RuntimeError("codex unavailable")
        assert kwargs["max_budget"] == 0.25
        return SimpleNamespace(cost=0.1)

    monkeypatch.setattr("llm_client.codex_canary.acall_llm", fake_call)
    queue = CodexCanaryQueue.for_trusted_async_work(
        _config(
            tmp_path,
            fallback_model="gpt-5.6",
            fallback_provider="openai_api",
            fallback_spend_ceiling_usd=0.25,
        )
    )
    receipt = await queue.submit(_job("canary-fallback"))
    await queue.close()

    assert models == ["codex/gpt-5.6-luna", "gpt-5.6"]
    assert receipt.fallback_used is True
    assert receipt.fallback_tag == "explicit_fallback:openai_api"


@pytest.mark.asyncio
async def test_job_quota_is_rejected_with_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr("llm_client.codex_canary.ObservedRun", _FakeRun)
    queue = CodexCanaryQueue.for_trusted_async_work(_config(tmp_path, max_jobs=1))

    async def fake_call(model, messages, **kwargs):
        return SimpleNamespace(cost=0.0)

    monkeypatch.setattr("llm_client.codex_canary.acall_llm", fake_call)
    first = await queue.submit(_job("canary-one"))
    second = await queue.submit(_job("canary-two"))
    await queue.close()

    assert first.status == "succeeded"
    assert second.status == "rejected"
    assert queue.telemetry().rejected == 1
