---
type: source
title: Revision c2f3693 Capsule Ingest
description: Historical capsule verification and its relationship to the previously accepted base capsule.
created: 2026-08-16
updated: 2026-08-22
sources: [../../raw/source-manifest.json, ../../raw/source-manifest-fc5ee7f-company-f4a08fe.json, revision-f194028.md]
confidence: high
---

# Historical source binding

At the time of this ingest, the wiki described personal upstream
`BrianMills2718/llm_client` at commit
`c2f3693a7a8f1f2e211368c189a64df69dcb381f`, Git tree
`57cf3a89ed3e8b4c3d955c5bbdec4dd87ccb7c77`. This revision advanced while the
wiki branch was being prepared. Its delta from the accepted capsule base
changes the trace-family observability query and related API reference/tests;
the wiki therefore ingested the new revision before integration rather than
quietly claiming the earlier source was current.

# Capsule verification

The maintained generator was rerun from the exact remote-default tree without
reading mutable checkout files. It produced verification capsule
`sha256:8f7e46e5...49aced1`: 155 Python files, 155 modules, 1,079 public symbols,
zero omissions, 2,319,183 source bytes, and 778,147 capsule bytes. The bytes
were verified but not published as a new Project Meta artifact in this unit;
the complete receipt is in [`raw/source-manifest.json`](../../raw/source-manifest.json).
This was an exact remote-default generator verification, not a newly accepted
Project Meta reconciliation/capsule release. The manifest preserves that
limitation instead of promoting the temporary output to maintained authority.

The earlier content-addressed
[revision `f194028` capsule](revision-f194028.md) remains the accepted Project
Meta artifact and provenance base. It is not mislabeled as current.

Plan 359's [dual-lineage manifest](../../raw/source-manifest-fc5ee7f-company-f4a08fe.json)
superseded the original manifest for freshness checks at that time. It confirms that
the selected personal Python/config surface still matches this exact source
revision while adding current authority hashes and the separate company
capsule. The original manifest remains immutable evidence of this ingest.

Revision `917318b` now owns the [current source binding](revision-917318b.md).
This page and both older manifests remain lineage evidence rather than
current-source authority.

# Limits

Capsules contain definitions, signatures, docstrings, typing state, and source
anchors—not calls, imports, runtime state, deployment state, or provider health.
Workflow relationships in this wiki were checked directly in that historical
source. A future Project Meta refresh can publish a newer verified capsule
without changing this authority boundary.

# Citations

1. [Pinned source tree](https://github.com/BrianMills2718/llm_client/tree/c2f3693a7a8f1f2e211368c189a64df69dcb381f)
2. [Pinned trace query source](https://github.com/BrianMills2718/llm_client/blob/c2f3693a7a8f1f2e211368c189a64df69dcb381f/llm_client/observability/query.py)
3. [`source-manifest.json`](../../raw/source-manifest.json)
4. [Historical dual-lineage manifest](../../raw/source-manifest-fc5ee7f-company-f4a08fe.json)
