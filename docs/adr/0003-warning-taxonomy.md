# ADR 0003: Warning Taxonomy

Status: Accepted
Date: 2026-02-22
Last verified: 2026-07-13
Verification context: async safety expiry remains a typed terminal failure rather than a warning; malformed safety configuration emits a visible operational log and retains the finite default.

## Context

Current warnings include both model deprecation and model advisories
(outclassed-but-allowed). Warning category drift has caused test and contract
mismatch.

## Decision

1. `DeprecationWarning` is reserved for true deprecation/blocking paths.
2. `UserWarning` is used for outclassed-but-allowed advisories.
3. Week 1 locks category semantics; code identifiers can be added later.
4. Week 1 applies only drift fixes needed to align behavior/tests with this
   taxonomy.

## Rationale

Category consistency improves automation and human interpretation.

## Consequences

Positive:
1. Clear operational meaning of warnings.
2. Stable tests and less ambiguity in tool/agent behavior.

Negative:
1. Existing tests expecting different categories must be updated intentionally.

## Follow-up

Add stable warning codes (`LLMC_WARN_*`) with structured metadata once
router/kernel contracts are stabilized.
