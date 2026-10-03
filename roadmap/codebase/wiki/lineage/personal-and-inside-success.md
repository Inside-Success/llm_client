---
type: lineage
title: Personal and Inside Success Repository Lineage
description: Inside-Success/llm_client is independent and canonical for Inside Success since 2026-10-03; the former personal upstream is ancestry only.
created: 2026-08-16
updated: 2026-10-03
sources: [../../../../docs/plans/105_inside_success_fork_reconciliation.md, ../sources/revision-fe581ed.md, ../sources/revision-5228ceb.md, ../sources/revision-4f7ecfa.md, ../sources/inside-success-f4a08fe.md, ../../raw/source-manifest-5228ceb-inside-success.json]
confidence: high
---

# Current relationship (2026-10-03)

`Inside-Success/llm_client` is independent and canonical for Inside Success.
It was disconnected from its former personal upstream, `BrianMills2718/llm_client`,
on 2026-10-03 because the upstream maintainer, Brian Mills, left Inside Success on
2026-10-02. There is no sync in either direction: do not merge, port, or
backport from the former upstream, and do not open pull requests to it. The
revision facts below are history. The last capsule-backed company source is
`f4a08fe`; the last freshly observed company default branch in a wiki ingest
was `926599c` (2026-08-23). The current wiki ingest is bound to canonical `Inside-Success/llm_client`
revision `5228ceb` (see [source ingest](../sources/revision-5228ceb.md)).

# Two identities

| Repository | Role | Ownership boundary |
| --- | --- | --- |
| `Inside-Success/llm_client` | Canonical Inside Success repository (independent since 2026-10-03) | Inside Success governance; all company changes land here through its own reviewed pull requests |
| `BrianMills2718/llm_client` | Former personal upstream (until 2026-10-03) | Brian-owned and separate; ancestry only, not a sync source or contribution target. Described only by the historical ingest [`4f7ecfa`](../sources/revision-4f7ecfa.md) |

These are not one repository and are not merged into one ownership domain.
The rest of this section and the tables below record the relationship before
2026-10-03.
They can contain equivalent code trees while retaining different commit IDs,
ancestry, branch controls, credentials, and publication authority. Plan 105
reconciled earlier divergence by preserving unique history, adapting reviewed
company fixes into the personal canonical line, and advancing the company line
through normal reviewed Git integration. Its accepted equality criterion was
identical Git trees with the personal commit as an ancestor, not necessarily
identical commit SHAs.

# Wiki treatment

Before 2026-10-03 the wiki bound both sources independently (history; the current binding is the single canonical `fe581ed` source):

| Source | Revision | Tree | Capsule state |
| --- | --- | --- | --- |
| Personal upstream | `4f7ecfa` | `e9dfd48` | Exact current source-surface verification; maintained accepted base capsule remains `f194028` |
| Company downstream analyzed source | `f4a08fe` | `feca132` | Maintained Project Meta capsule and passing 16-anchor receipt |
| Company downstream live branch | `926599c` | Not ingested | Fresh remote identity only; no capsule-backed source synthesis in this wiki |

The company remote was freshly observed at `926599c` during the 2026-08-23
ingest. The analyzed company material remains pinned to accepted capsule source
`f4a08fe`; claims below do not project that older analysis onto the newer
branch. Neither observation proves a deployed version. Deployment still
requires live runtime evidence.

# Exact divergence at the pinned revisions

The two revisions have common ancestor `be189820d1412ec4d19ba148ed1cbdf79c387b3d`.
Git reports 7 personal-only and 20 company-only commits after that ancestor, so
the current relationship is **diverged**, not equal or simple behind/ahead.

Across the capsule-selected `llm_client` and `pyproject.toml` surface, nine
package paths differ: eight modified files and one company-only file. Moving
from personal `c2f3693` to company `f4a08fe` yields 105 insertions and 206
deletions:

| Path | Exact source-level distinction |
| --- | --- |
| `llm_client/inside_success_policy.py` | Company-only model allowlist and hard-block exceptions for reviewed Inside Success routes |
| `llm_client/core/model_execution_policy.py` | Company imports and unions the organization overlay into the generic allowlist |
| `llm_client/execution/call_contracts.py` | Company applies the overlay's hard-block exceptions |
| `llm_client/execution/structured_runtime.py` | Personal retains newer Codex subprocess-deadline propagation |
| `llm_client/execution/text_runtime.py` | Personal retains newer Codex subprocess-deadline propagation |
| `llm_client/sdk/agents_codex.py` | Personal retains the environment-configurable hard deadline and explicit validation |
| `llm_client/observability/query.py` | Personal retains the newer indexed rooted trace-family query option |
| `llm_client/openrouter_generation.py` | Personal retains inline OpenRouter provider-evidence construction |
| `llm_client/route_certification_runtime.py` | Personal prefers inline provider evidence before endpoint-history fallback |

This table describes source at two exact commits. It does not decide whether
the company overlay should move upstream, whether newer personal changes should
move downstream, or whether either repository should replace the other. Any
such action still requires reviewed integration under the separate ownership
rules.

See [Revision 4f7ecfa source ingest](../sources/revision-4f7ecfa.md) for the
personal binding, [Inside Success revision f4a08fe](../sources/inside-success-f4a08fe.md)
for the company binding, and [Architecture](../architecture.md) for the personal
code relationships.

# Citations

1. [Plan 105 reconciliation authority at `c2f3693`](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/docs/plans/105_inside_success_fork_reconciliation.md)
2. [Personal comparison source revision on GitHub](https://github.com/BrianMills2718/llm_client/tree/c2f3693a7a8f1f2e211368c189a64df69dcb381f)
3. [Current canonical source binding](../../raw/source-manifest-fe581ed-inside-success.json)
4. [Company source tree](https://github.com/Inside-Success/llm_client/tree/f4a08fec950c8d973194e904ac3834e1e255166d)
5. [Company-only policy overlay](https://github.com/Inside-Success/llm_client/blob/f4a08fec950c8d973194e904ac3834e1e255166d/llm_client/inside_success_policy.py)
6. [Personal Codex deadline source](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/sdk/agents_codex.py)
7. [Personal trace-query source](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/observability/query.py)
8. [Personal OpenRouter evidence source](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/openrouter_generation.py)
