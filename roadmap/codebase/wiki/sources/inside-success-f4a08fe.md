---
type: source
title: Inside Success Revision f4a08fe Source Ingest
description: Exact organization-owned downstream capsule, provenance, comparison boundary, and freshness limits.
created: 2026-08-16
updated: 2026-08-16
sources: [../../raw/source-manifest-fc5ee7f-company-f4a08fe.json, ../lineage/personal-and-inside-success.md]
confidence: high
---

# Company source binding

The maintained Project Meta path identifies `Inside-Success/llm_client` as
`inside-success-llm-client`, with `owner_class: organization`. Its capsule is
bound to remote-default commit
`f4a08fec950c8d973194e904ac3834e1e255166d` and tree
`feca132a3436ad203542aa006fad9035332568fb`. This is a separate source from the
[personal `c2f3693` ingest](revision-c2f3693.md), not an alias for it.

The source binding came from the maintained `brian-core` network observation.
At that observation, the existing company checkout was clean and 38 commits
behind the remote. Its HEAD, status digest, and refs were unchanged by the
observation. That local-checkout fact is historical evidence for generation;
it does not establish current checkout or deployment state.

# Capsule coverage

| Measure | Company downstream |
| --- | ---: |
| Python source files/modules | 156 |
| Public symbols | 1,081 |
| Parser omissions | 0 |
| Source UTF-8 bytes | 2,316,067 |
| Capsule UTF-8 bytes | 780,931 |

The capsule ID is
`sha256:8ea32e7fc5ada07671fe161402d12a9b08817c19bda5c804326354f09cb0be6a`.
Two generations were byte-identical, and the checked-in receipt reopens 16
evenly sampled public-symbol anchors at the exact company revision. The
capsule was committed to Project Meta at `2eb60578`; its generator code is
identified separately at `fbc1f4e7`.

# What differs from personal upstream

At the pinned personal and company revisions, the source surfaces differ in
nine `llm_client` paths. The company tree adds
`llm_client/inside_success_policy.py`, whose source docstring defines an
Inside Success model-policy overlay for the Grounded Research consumer. The
other eight paths differ in model-policy integration, Codex process deadlines,
trace-family queries, and OpenRouter route-evidence handling. These are exact
source differences, not evidence about which code is deployed or which branch
should replace the other.

Use [Personal and Inside Success repository lineage](../lineage/personal-and-inside-success.md)
for the exact ancestry and path comparison.

# Limits

The capsule contains source-derived definitions, signatures, docstrings,
typing state, and anchors. It does not prove deployment, runtime health,
consumer adoption, or a decision to synchronize either direction. The full
freshness check can prove whether the declared company remote tip is still
current; if network access is unavailable, that boundary fails visibly.

# Citations

1. [Immutable dual-lineage manifest](../../raw/source-manifest-fc5ee7f-company-f4a08fe.json)
2. [Company source tree at `f4a08fe`](https://github.com/Inside-Success/llm_client/tree/f4a08fec950c8d973194e904ac3834e1e255166d)
3. [Company policy overlay at `f4a08fe`](https://github.com/Inside-Success/llm_client/blob/f4a08fec950c8d973194e904ac3834e1e255166d/llm_client/inside_success_policy.py)
4. [Maintained Project Meta capsule](https://github.com/BrianMills2718/project-meta/blob/2eb60578c67f0e477a8c73acba89fe250fc86aff/generated/repository_capsules/inside-success-llm-client/8ea32e7fc5ada07671fe161402d12a9b08817c19bda5c804326354f09cb0be6a.json)
5. [Passing 16-anchor receipt](https://github.com/BrianMills2718/project-meta/blob/2eb60578c67f0e477a8c73acba89fe250fc86aff/generated/repository_capsules/inside-success-llm-client/anchor-receipt.json)
6. [Project Meta Plan 243 downstream-capsule receipt](https://github.com/BrianMills2718/project-meta/blob/2eb60578c67f0e477a8c73acba89fe250fc86aff/docs/plans/243_agent-ready-ecosystem-workspace-and-documentation.md)
