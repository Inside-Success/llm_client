"""Targeted noise filter for litellm's background LoggingWorker.

Why this exists
---------------
litellm's LoggingWorker (``litellm_core_utils/logging_worker.py``,
``_process_log_task``) wraps every observability callback in
``asyncio.wait_for`` and logs ANY failure via ``verbose_logger.exception``,
producing a full ERROR traceback on the ``LiteLLM`` logger. When a logging
coroutine is cancelled or times out at event-loop teardown (routine during
process shutdown or loop switches), the caller gets a scary
``LoggingWorker error:`` traceback (CancelledError/TimeoutError family) for a
condition that is benign, internal to litellm, and outside the caller's
control.

Verified unfixed upstream as of 2026-07-14: the unconditional
``verbose_logger.exception(f"LoggingWorker error: {e}")`` is present verbatim
in litellm 1.88.1, 1.91.1, and current ``main``. An upstream issue has been
drafted (see grounded-research ``research/BUILD_LOG.md``, Session 35); this
filter is the local mitigation until a fixed release exists.

What it suppresses — and ONLY this
----------------------------------
A record is dropped only when ALL of these hold:

1. it was emitted from ``logging_worker.py`` (``record.module``),
2. its message starts with ``"LoggingWorker error"``, and
3. its attached exception is CancelledError or TimeoutError.

Every other record on the ``LiteLLM`` logger passes through untouched —
including OTHER LoggingWorker errors (e.g. a ValueError raised by a callback),
which remain fully visible. This is deliberately NOT a blanket mute.
"""

from __future__ import annotations

import asyncio
import logging

_LITELLM_LOGGER_NAME = "LiteLLM"

# TimeoutError from wait_for expiry; CancelledError for direct cancellation.
# (asyncio.TimeoutError is an alias of TimeoutError on Python >= 3.11 but is
# a distinct class on 3.10, so both spellings are listed.)
_SUPPRESSED_EXC_TYPES: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    TimeoutError,
    asyncio.TimeoutError,
)


class LiteLLMLoggingWorkerNoiseFilter(logging.Filter):
    """Drop LoggingWorker cancellation/timeout tracebacks; pass everything else."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        if record.module != "logging_worker":
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not message.startswith("LoggingWorker error"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, _SUPPRESSED_EXC_TYPES):
            return False
        return True


_INSTALLED = False


def install_litellm_logging_worker_noise_filter() -> None:
    """Install the filter on the ``LiteLLM`` logger. Idempotent.

    Called once at llm_client import time (``core/client.py``, next to the
    other litellm global configuration). Logger-level filters only apply to
    records logged directly through that logger, which is exactly how
    litellm's ``verbose_logger`` emits.
    """
    global _INSTALLED  # noqa: PLW0603
    if _INSTALLED:
        return
    target = logging.getLogger(_LITELLM_LOGGER_NAME)
    if not any(isinstance(f, LiteLLMLoggingWorkerNoiseFilter) for f in target.filters):
        target.addFilter(LiteLLMLoggingWorkerNoiseFilter())
    _INSTALLED = True
