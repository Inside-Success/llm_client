# Plan #364: Codex Account Identity Receipts

**Status:** Implemented — WhyGame downstream acceptance pending
**Priority:** Critical
**Blocks:** deterministic multi-account Codex consumers, beginning with WhyGame Reboot

## Outcome

A ChatGPT-authenticated Codex call records whether authentication came from an
explicit or ambient home and retains a stable SHA-256 digest of the executing
account ID in its public call-lifecycle events. Tokens, raw account IDs, email
addresses, and filesystem paths never enter observability.

## Implementation

1. Resolve privacy-bounded Codex identity evidence before runtime dispatch.
2. Attach the binding mode and account digest to started and terminal lifecycle
   events so provider failures remain attributable.
3. Preserve API-key compatibility by allowing an absent ChatGPT account digest.
4. Require downstream consumers that need deterministic account routing to pass
   an explicit caller-owned `codex_home`.

## Acceptance

- A forced failed Luna call retains `codex_auth_binding=explicit` and the
  expected account digest on both lifecycle events.
- The retained payload contains no account ID, token, or profile path.
- Existing lifecycle and Codex adapter tests remain green.
