# Plan 102 Progress

## Mission

Add opt-in exact raw structured-attempt sidecars and an exact-logical-call
reader so onto-canon6 Plan 0141 can verify transport bytes without confusing
normalized parsed content with provider raw content.

## Acceptance

- retention remains off by default and invalid configuration fails loudly;
- enabled storage is checked before provider dispatch;
- exact bytes are private, contained, hash-bound, atomically written, expired
  reads fail, and cleanup remains agent-invocable after collection is disabled;
- the public reader selects only through the Plan 101 exact receipt and rejects
  absence or tampering;
- sync/async success, retry, and fallback paths retain every received attempt;
- no provider call or semantic judgment occurs;
- focused and repository gates pass, followed by independent exact-commit
  review and a verified commit/push.

## Current State

- [x] Existing Plan 97/101 contracts and coupled ADRs reviewed.
- [x] Plan 102 contract written.
- [x] Provider-free failing tests added.
- [x] Sidecar storage and exact reader implemented.
- [x] Native structured runtime wired.
- [x] Focused and repository verification complete.
- [x] Independent review accepted.
- [ ] Merged and downstream dependency pinned.

## Verification Snapshot

- 71 focused provider-free runtime/receipt/artifact tests pass after repairing
  the first independent review's symlink-substitution and disabled-cleanup
  blockers. The three original counterexample controls pass directly.
- Changed files pass Ruff; the three Plan 102 observability modules pass strict
  mypy.
- Generated API references are current; their generator check and 11 API/public
  surface tests pass.
- The repo-local full suite passes: 1,695 passed, 3 skipped, 11 deselected.
- Canonical whole-repository `make lint` is inherited red with 309 findings;
  none are in the changed Plan 102 files, which pass their scoped Ruff check.
- Canonical whole-package `make typecheck` is inherited red in this environment
  with 209 errors across 40 files; none originate in the new raw-artifact or
  selected-reader modules. This does not count as a passing repository gate.
- The pre-repair exact commit `d6ae314` was independently rejected. Direct
  replay accepted both blocker repairs at `fce9118`; a final narrow review
  accepted exact `6e53919` after normalizing impossible-date failures to the
  documented typed error.
- No provider or model call occurred.

## Independent Review Resolution

The first review rejected two operational gaps: a duplicate-write path followed
a matching-byte final symlink, and cleanup stopped being reachable after raw
collection was disabled. The accepted repair uses `lstat`, `O_NOFOLLOW`, and
inode matching without chmodding existing targets; rejects expired references
at read time; and exports agent-invocable cleanup that remains available after
collection stops. Documentation explicitly disclaims any background timer.

The reviewer directly replayed both original counterexamples and the final
impossible-date typed-error control before accepting exact `6e53919`.

## Constraints

Provider/model calls are unauthorized. This is trusted-process provenance, not
provider attestation. Semantic judgments remain outside deterministic code.
