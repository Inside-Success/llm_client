# llm_client Codebase Wiki — Schema

This directory is a Karpathy-style, agent-maintained wiki about the architecture
and operation of `llm_client`. Read this file fully before ingesting, querying,
or changing the wiki.

## Purpose

Help coding agents understand the complete repository without loading every
file. Begin at `wiki/index.md`, follow the smallest relevant reading path, and
reopen native code or authority documents for exact claims. A useful answer
explains relationships and boundaries, cites its source revision, states gaps,
and avoids confusing generated discovery data with source truth.

## Three layers

- `raw/` contains immutable source manifests and revision pins. Do not edit a
  manifest in place; add a new revision manifest and supersede the old ingest.
- `wiki/` contains derived, interlinked Markdown maintained by agents.
- `CLAUDE.md` is this operating schema. User corrections belong here so future
  sessions do not repeat the same misunderstanding.

The repository code itself remains the authoritative raw source. The manifest
pins the exact Git tree and the separately maintained capsule rather than
duplicating either inside the wiki.

## Directory map

```text
raw/                         immutable revision and capsule manifests
wiki/
  index.md                   first read for every query
  log.md                     append-only ingest/query/lint chronicle
  overview.md                repository synthesis and boundary map
  architecture.md            main component and data-flow map
  sources/                   summaries of ingested source sets
  concepts/                  durable concepts and runtime contracts
  packages/                  package-level responsibility maps
  workflows/                 end-to-end execution paths
  lineage/                   ownership, upstream, and downstream relationships
```

## Page contract

Every page except `index.md` and `log.md` has YAML frontmatter with:

```yaml
type: overview | architecture | source | concept | package-map | workflow | lineage
title: Human-readable title
description: One sentence used by the index
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
confidence: high | medium | low | speculative
```

Use relative Markdown links. Prefer structured headings, tables, and small
flows. Every non-obvious claim cites either an exact GitHub revision/line range,
an authoritative repository document, or the pinned capsule source summary.

## Query

1. Read `wiki/index.md` first.
2. Read only the relevant overview, workflow, concept, package, or lineage
   pages.
3. Reopen linked native source for exact behavior, signatures, configuration,
   or change recommendations.
4. State confidence and gaps. File a reusable answer back into the wiki and
   append `wiki/log.md` when it adds a durable relationship.

## Ingest

1. Add a content-addressed manifest in `raw/` for the exact source tree and
   capsule; never scan a mutable tree while claiming revision-bound knowledge.
2. Summarize the source in `wiki/sources/`.
3. Update all affected concept, package, workflow, architecture, and lineage
   pages. Flag contradictions and supersession rather than silently overwriting.
4. Update `wiki/index.md` and prepend an entry to `wiki/log.md`.
5. Run deterministic lint, then inspect changed pages for contradiction,
   missing concepts, and unsupported relationships.

## Lint

Run:

```bash
python3 "${PROJECTS_ROOT:-$HOME/code/active}/agent-skills/skills/karpathy-wiki/scripts/lint.py" roadmap/codebase/wiki
```

Then inspect source-backed consistency manually. Every finding receives either
an immediate fix or an explicit owner and next source event.

## House rules

- The requested product is the interlinked codebase wiki. A capsule or UI over
  symbols is supporting infrastructure and must never be presented as the wiki.
- Cover the whole repository at an appropriate compression level; do not imply
  that one example function represents the entire codebase.
- Types and docstrings are extraction inputs. Wiki pages must add relationships,
  concepts, workflows, boundaries, and uncertainty without inventing behavior.
- Keep `BrianMills2718/llm_client` and `Inside-Success/llm_client` as distinct
  repository identities. Describe synchronization or ancestry explicitly; do
  not call them the same repository.
- Source wins over capsule; capsule wins over wiki prose for extracted facts.
- Do not infer runtime health, deployment state, or provider behavior from the
  source-only wiki.
