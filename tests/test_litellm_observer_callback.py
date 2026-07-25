"""Usage-accounting tests for the catch-all LiteLLM observer."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from llm_client.litellm_observer_callback import LLMClientObserverCallback


def test_standard_logging_object_preserves_bounded_usage_details() -> None:
    callback = LLMClientObserverCallback()
    started = datetime.now(timezone.utc)
    kwargs = {
        "model": "openrouter/test",
        "messages": [{"role": "user", "content": "test"}],
        "litellm_params": {"metadata": {"trace_id": "usage.callback"}},
        "standard_logging_object": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
            "prompt_tokens_details": {
                "cached_tokens": 4,
                "reasoning": "must not persist",
            },
            "completion_tokens_details": {
                "reasoning_tokens": 3,
                "reasoning": "must not persist",
            },
            "response_cost": 0.001,
        },
    }

    with patch("llm_client.io_log.log_call") as log_call:
        callback.log_success_event(
            kwargs,
            response_obj=None,
            start_time=started,
            end_time=started + timedelta(seconds=1),
        )

    usage = log_call.call_args.kwargs["result"].usage
    assert usage["cached_tokens"] == 4
    assert usage["reasoning_tokens"] == 3
    assert usage["prompt_tokens_details"] == {"cached_tokens": 4}
    assert usage["completion_tokens_details"] == {"reasoning_tokens": 3}
    assert "must not persist" not in str(usage)
