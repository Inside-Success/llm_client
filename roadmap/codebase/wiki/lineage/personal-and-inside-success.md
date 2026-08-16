---
type: lineage
title: Personal and Inside Success Repository Lineage
description: Ownership and synchronization boundaries between Brian's canonical upstream and the company downstream.
created: 2026-08-16
updated: 2026-08-16
sources: [../../../../docs/plans/105_inside_success_fork_reconciliation.md, ../sources/revision-c2f3693.md]
confidence: high
---

# Two identities

| Repository | Role | Ownership boundary |
| --- | --- | --- |
| `BrianMills2718/llm_client` | Personal canonical implementation upstream | Brian-owned; this is the repository and revision described by the current wiki ingest |
| `Inside-Success/llm_client` | Organization-owned downstream | Inside Success governance; changes travel through reviewed company integration rather than silently rewriting the personal line |

These are not one repository and are not merged into one ownership domain.
They can contain equivalent code trees while retaining different commit IDs,
ancestry, branch controls, credentials, and publication authority. Plan 105
reconciled earlier divergence by preserving unique history, adapting reviewed
company fixes into the personal canonical line, and advancing the company line
through normal reviewed Git integration. Its accepted equality criterion was
identical Git trees with the personal commit as an ancestor, not necessarily
identical commit SHAs.

# Wiki treatment

The current source manifest binds only to the personal upstream at `c2f3693`.
It must not be used to claim that the company downstream is presently at the
same tree or deployment state; that would require a fresh remote observation
and, for deployment, live runtime evidence. A future company capsule should be
a separate source ingest with its own repository ID and revision. A comparison
page may then describe exact drift without collapsing identities.

See [Revision c2f3693 source ingest](../sources/revision-c2f3693.md) for the
current binding and [Architecture](../architecture.md) for code relationships.

# Citations

1. [Plan 105 reconciliation authority at `c2f3693`](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/docs/plans/105_inside_success_fork_reconciliation.md)
2. [Personal source revision on GitHub](https://github.com/BrianMills2718/llm_client/tree/c2f3693a7a8f1f2e211368c189a64df69dcb381f)
3. [Current wiki source binding](../../raw/source-manifest.json)
