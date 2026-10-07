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

## Where ADRs live

ADR bodies are sections of [DECISIONS.md](DECISIONS.md) (one file, to keep the
repository under its 100-Markdown-file cap). Each section starts with an
explicit anchor `<a id="NNNN-title"></a>`, the old per-file name without `.md`.
Only `0015-provider-governance-and-shared-coordination.md` remains a separate
file, because a hash-pinned codebase-wiki source links to it.

## Creating an ADR

1. Append a section to `DECISIONS.md`: `<a id="NNNN-title"></a>`, then
   `## ADR NNNN: Title`, then the template body with its headings one level
   lower (`###`). Add it to the Contents list at the top.
2. Fill in sections
3. Add to the index in `README.md`, linking `DECISIONS.md#NNNN-title`
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
