---
id: inside-success-llm-client-wiki-index
type: index
title: "Inside Success LLM Client wiki front door"
status: authored
authority: derived
owner: Inside-Success/llm_client
as_of: 2026-10-03
visibility: unknown
source_of_truth: false
---

# Inside Success LLM Client

Front door for `Inside-Success/llm_client`. Orientation only: every claim here is routed to the native file that owns it, and that file wins when they differ. Read this page before searching the repository.

## What this repository is

A unified LLM client with mandatory observability, cost tracking and policy enforcement, built on LiteLLM ([README](../README.md)). The project dossier is `PROJECT.md`. The repo is independent and canonical for Inside Success since 2026-10-03; `BrianMills2718/llm_client` is the former personal upstream, kept as ancestry only: do not sync, merge or port from it ([AGENTS.md](../AGENTS.md), "Repository Identity").

## Where live docs are

- Operating rules: [AGENTS.md](../AGENTS.md)
- What `llm_client` owns versus consumes from other repos: `docs/ops/CAPABILITY_DECOMPOSITION.md`
- Plans and delivery status (the status owner): [plan index](../docs/plans/AGENTS.md)
- Architecture decisions: [ADR index](../docs/adr/README.md)
- Architecture orientation (source-bound codebase wiki) and the plans/codebase navigation split: [roadmap](../roadmap/README.md)
- Documentation directory front door: [docs/README.md](../docs/README.md) (routes to every doc, guide and subtree rule file)
- Open issues: `ISSUES.md`; shared agent findings: `KNOWLEDGE.md`; changes: `CHANGELOG.md`

## Superseded or point-in-time

- `docs/HANDOFF.md` is a point-in-time record (2026-07-25, revision 5a3369e); its own banner says the plan index wins on status.
- ADR 0008 is marked Superseded in the [ADR index](../docs/adr/README.md).
- Do not treat the codebase wiki as proof of an exact signature; reopen the native source ([AGENTS.md](../AGENTS.md), rule 9).

## Code and how to run

- Implementation lives in the Python package [llm_client/](../llm_client/); [src/](../src/) holds only a routing README to it. Tests: [tests/](../tests/).
- Install, test and check commands are targets in the [Makefile](../Makefile): `make install` (editable install with dev extras), `make test`, `make lint`, `make typecheck`, `make codebase-wiki-check`, and `make check` (all of these). Packaging: [pyproject.toml](../pyproject.toml). Usage examples: [README](../README.md).

## Coverage and limits

- This page is hand-authored from the repository's own files on 2026-10-03; it is not a reviewed enrichment pass and does not summarise the plan files.
- `make codebase-wiki-check` passes on `main` as of 2026-10-03 after the wiki was re-ingested from `Inside-Success/llm_client` revision `5228ceb` (manifest `roadmap/codebase/raw/source-manifest-98c9333-inside-success.json`). The codebase-wiki concept and workflow pages still cite older revisions; see the source ingest page under [roadmap](../roadmap/README.md). Owner of the next gap: this repository's maintainers, tracked through the [plan index](../docs/plans/AGENTS.md).

## If this page did not answer your question

Find the answer, then **add the route here before you finish the work that made you look**. A wiki that is only ever read decays; this is the only mechanism by which it improves, and the gap is cheapest to close while you still have the answer in front of you.

- Add **where the answer lives**, not an essay.
- If what you found contradicts this page, fix it or mark it stale; leaving both is worse than either.
- If the answer belongs to a native authority, link that authority rather than copying its content here.
