# Plan 102 Progress

## Mission

Add opt-in exact raw structured-attempt sidecars and an exact-logical-call
reader so onto-canon6 Plan 0141 can verify transport bytes without confusing
normalized parsed content with provider raw content.

## Acceptance

- retention remains off by default and invalid configuration fails loudly;
- enabled storage is checked before provider dispatch;
- exact bytes are private, contained, hash-bound, atomically written, and
  retention-bounded;
- the public reader selects only through the Plan 101 exact receipt and rejects
  absence or tampering;
- sync/async success, retry, and fallback paths retain every received attempt;
- no provider call or semantic judgment occurs;
- focused and repository gates pass, followed by independent exact-commit
  review and a verified commit/push.

## Current State

- [x] Existing Plan 97/101 contracts and coupled ADRs reviewed.
- [x] Plan 102 contract written.
- [ ] Provider-free failing tests added.
- [ ] Sidecar storage and exact reader implemented.
- [ ] Native structured runtime wired.
- [ ] Focused and repository verification complete.
- [ ] Independent review accepted.
- [ ] Merged and downstream dependency pinned.

## Constraints

Provider/model calls are unauthorized. This is trusted-process provenance, not
provider attestation. Semantic judgments remain outside deterministic code.

