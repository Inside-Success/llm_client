"""Inside Success downstream model-policy overlay.

The personal repository remains the reusable implementation upstream. This
module contains the one company-owned policy difference required by the
Grounded Research consumer: its reviewed production and subscription seats are
allowed to execute even when the generic upstream has retired those models.
"""

# Machine-readable human acceptance for model-policy auditing.
model_override_acceptance = {
    "accepted_by": "Brian Mills",
    "reason": (
        "Preserve the active, benchmark-selected Grounded Research model roster "
        "while Inside Success consumes the synchronized generic runtime."
    ),
}


# Exact additional routes used by Grounded's production, OpenRouter, testing,
# fallback, or subscription-lane configuration. Generic upstream routes are not
# repeated here; the core policy unions this downstream overlay with them.
INSIDE_SUCCESS_ADDITIONAL_EXECUTION_MODELS: frozenset[str] = frozenset(
    {
        "claude-code/claude-opus-4-8",  # model-policy: allow-raw-model
        "claude-code/claude-sonnet-4-6",  # model-policy: allow-raw-model
        "claude-code/claude-sonnet-5",  # model-policy: allow-raw-model
        "codex/gpt-5-nano",  # model-policy: allow-raw-model
        "codex/gpt-5.4-mini",  # model-policy: allow-raw-model
        "codex/gpt-5.4-nano",  # model-policy: allow-raw-model
        "codex/gpt-5.5",  # model-policy: allow-raw-model
        "openrouter/anthropic/claude-opus-4.8",  # model-policy: allow-raw-model
        "openrouter/anthropic/claude-sonnet-4.6",  # model-policy: allow-raw-model
        "openrouter/anthropic/claude-sonnet-5",  # model-policy: allow-raw-model
        "openrouter/google/gemini-2.5-flash",  # model-policy: allow-raw-model
        "openrouter/google/gemini-2.5-flash-lite",  # model-policy: allow-raw-model
        "openrouter/google/gemini-3.1-flash-lite",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.4-mini",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.4-nano",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.5",  # model-policy: allow-raw-model
    }
)


# Exact routes above that intentionally override a generic hard-block pattern.
# Sonnet, Gemini, and GPT-5 Nano routes need only the execution allowlist.
INSIDE_SUCCESS_HARD_BLOCK_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "claude-code/claude-opus-4-8",  # model-policy: allow-raw-model
        "codex/gpt-5.4-mini",  # model-policy: allow-raw-model
        "codex/gpt-5.4-nano",  # model-policy: allow-raw-model
        "codex/gpt-5.5",  # model-policy: allow-raw-model
        "openrouter/anthropic/claude-opus-4.8",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.4-mini",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.4-nano",  # model-policy: allow-raw-model
        "openrouter/openai/gpt-5.5",  # model-policy: allow-raw-model
    }
)
