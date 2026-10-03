# Architecture Decision Records

ADRs document significant architectural decisions.

## ADR Index

The index lives in [README.md](README.md) (ADRs 0001-0016; the number 0015 is
used by two ADRs, so the next number is 0017). Keep it complete when adding or
superseding an ADR.

## ADR Lifecycle

```
Proposed → Accepted/Rejected → Superseded (optional)
```

## Creating an ADR

1. Copy template to `NNNN-title.md`
2. Fill in sections
3. Add to the index in `README.md`
4. Get review if needed

## ADR Template

```markdown
# ADR-NNNN: Title

Status: Proposed | Accepted | Rejected | Superseded by ADR-XXXX
Date: YYYY-MM-DD

## Context
What is the issue that we're seeing that motivates this decision?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or harder as a result of this decision?
```

## Status Meanings

| Status | Meaning |
|--------|---------|
| Proposed | Under discussion |
| Accepted | Decision made, being implemented |
| Rejected | Decided not to do this |
| Superseded | Replaced by a newer ADR, or made obsolete by a recorded code relocation (as ADR 0008) |

## Related

- `README.md` - ADR index and the 0015 duplicate-number note
