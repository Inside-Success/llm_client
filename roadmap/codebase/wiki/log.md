# Update Log

## 2026-10-03 (concept and workflow re-derivation)

- **Ingest** | Re-derived the six concept pages and two workflow pages from
  code at `Inside-Success/llm_client` revision `fe581ed` (tree `1accdb4`),
  covering the 3 new modules and 15 edited modules since `4f7ecfa`, and
  repointed every citation from the personal upstream to
  `Inside-Success/llm_client@fe581ed` with line ranges verified. New immutable
  manifest `raw/source-manifest-fe581ed-inside-success.json` (same code surface
  and digest as `5228ceb`, new source commit, same authority hashes); the
  freshness check default points to it, and `98c9333` is retained as history.
- **Update** | Added [revision fe581ed](sources/revision-fe581ed.md), updated
  the package map for the new modules, and marked the `5228ceb` page's
  "not re-derived" note as resolved. Prompt-assets page now covers the prompt
  context-contract and duplicate-content checks that were already in code.

## 2026-10-03 (authority re-pin)

- **Maintenance** | The documentation review edited hashed authority inputs
  (`AGENTS.md`, the capability and ecosystem documents). Added immutable
  manifest `raw/source-manifest-98c9333-inside-success.json` (same code
  surface and digest as `5228ceb`, source commit `98c9333`, new authority
  hashes) and pointed the freshness check at it. The `5228ceb` manifest is
  retained as history.

## 2026-10-03 (re-ingest)

- **Ingest** | Re-ingested from canonical `Inside-Success/llm_client` revision
  `5228ceb`, tree `1a0edc0`; new manifest
  `raw/source-manifest-5228ceb-inside-success.json` binds 169 surface files,
  digest `sha256:a29cd7f0...a662da`, and the current `AGENTS.md`-based
  authority set (the `CLAUDE.md` files were retired in #29). The freshness
  check default points to it. The earlier manifests are retained as history.
- **Update** | Refreshed package-map file counts (168 Python modules) and the
  lineage page; added [revision 5228ceb](sources/revision-5228ceb.md).
  Concept and workflow pages were not re-derived and still cite `4f7ecfa`.

## 2026-10-03

- **Lineage** | Recorded that `Inside-Success/llm_client` is independent and
  canonical for Inside Success; `BrianMills2718/llm_client` is the former
  personal upstream (maintainer left the company on 2026-10-02) and is no
  longer a sync source or contribution target. No source re-ingest was
  performed; the freshness check now reports the personal-bound manifest as
  non-canonical.

## 2026-08-23

- **Ingest** | Bound the current 166-file Python/config surface to source
  revision `4f7ecfa`, tree `e9dfd48`, and digest
  `sha256:c4a6aecf...f19a9475` after exact Codex CLI JSONL custody landed.
- **Update** | Distinguished normalized completed-item evidence from the exact
  decoded stdout stream and documented which one experiment authorities must
  validate and hash.
- **Lineage** | Freshly observed the Inside Success default branch at
  `926599c` while retaining `f4a08fe` as the last capsule-backed analyzed
  company source; no claims from the older capsule were projected forward.
- **Lint** | Deterministic source freshness, link structure, index coverage,
  and contradiction review passed for the revised pages.

## 2026-08-22

- **Ingest** | Bound the full Python/config surface to source revision
  `917318b`, tree `cfdb8d2`, 166 tracked surface files, and digest
  `sha256:72269551...3f0d83`; retained older capsule lineages without claiming
  they describe the current revision.
- **Update** | Documented exact Codex fresh/resume/fork transport, persistent
  home custody, identity receipts, and fail-loud streaming behavior.
- **Maintenance** | Recounted the current 165 Python modules by package and
  moved the default freshness check to the new immutable manifest.
- **Compatibility** | Advanced the current binding to `657a98f` after LiteLLM
  1.98.0 broke Python 3.10 imports; constrained only Python below 3.11 and
  retained the exact-session implementation at `917318b`.

## 2026-08-16

- **Ingest** | Added the separately owned Inside Success downstream at
  `f4a08fe` from maintained capsule `sha256:8ea32e7f...cb0be6a`; updated the
  lineage page with the exact diverged ancestry and nine-path source delta.
- **Maintenance** | Added immutable manifest 1.1 and deterministic freshness
  checks for the personal code surface, canonical authorities, exact Project
  Meta capsule blobs, and optional live company-remote verification.
- **Creation** | Created the repo-local codebase wiki after Brian clarified
  that the intended result was a Karpathy-style interlinked knowledge layer,
  not a symbol viewer.
- **Ingest** | Compiled personal upstream revision `c2f3693` and verified
  capsule `sha256:8f7e46e5...49aced1` into the overview, architecture, six
  concept pages, two workflow pages, the package map, and the personal/company
  lineage page; retained `f194028` and `sha256:a2584ec1...aad9` as base lineage.
- **Query** | Filed the canonical “what happens during `call_llm`?” reading
  path into [Text-call lifecycle](workflows/text-call-lifecycle.md).
- **Lint** | Structural health `100/100`; no broken links, orphans, thin pages,
  missing types, stale pages, or index drift. A separate source-reopen probe
  resolved 36 pinned citations and the exact capsule successfully.
