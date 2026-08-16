# Plan #358: Revision-Grounded Karpathy Codebase Wiki

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Fresh-session wiki-first architecture navigation for `llm_client`

## Outcome correction

Brian asked for a Karpathy-style representation of the codebase compiled from
typing and docstrings. Plan 243 produced the required revision-bound capsule,
but a capsule is a machine discovery index, not the requested interlinked wiki.
A temporary human viewer made the distinction visible but is not the product.

This plan creates the missing persistent wiki. A coding agent starts at one
index, follows architecture/concept/workflow links, and reopens exact source
before making an implementation claim.

## Sources and authority

- Current source repository: `BrianMills2718/llm_client` at
  `c2f3693a7a8f1f2e211368c189a64df69dcb381f`.
- Capsule lineage: accepted Project Meta base capsule
  `sha256:a2584ec1eec33473155366cec8e4e59fff0d022bc3473fb333c1a0f93832aad9`
  at `f194028`, followed by an exact current-tree verification capsule
  `sha256:8f7e46e598f7865d0d8a8273571d2ef3fb8ec1d1fc0eb904eaf8cc8d649aced1`.
- Architecture authority: `docs/ECOSYSTEM_TOP_DOWN_ARCHITECTURE.md` and
  `docs/ops/CAPABILITY_DECOMPOSITION.md`.
- Personal/company lineage authority: Plan 105 plus Project Meta repository
  governance. The repositories remain different ownership domains even when
  their trees are synchronized.

## Scope

1. Add a self-describing Karpathy-style bundle under `roadmap/codebase/` with
   immutable source pins, an agent schema, interlinked Markdown, a manifest,
   and an append-only log.
2. Cover the whole repository at package level while providing deeper pages
   for the public-call lifecycle, structured output, prompt assets,
   observability/budgets, tools/agents, and personal/company lineage.
3. Route new agents from the canonical root instruction and existing
   `roadmap/README.md` into the wiki.
4. Run deterministic wiki lint plus a source-reopen acceptance query.

## Boundaries

- The wiki is derived navigation, not API, architecture, policy, or runtime
  authority.
- The capsule provides definitions, signatures, docstrings, typing state, and
  anchors. Call relationships are verified in source and are not inferred from
  names.
- No provider call, deployment, package release, or Inside Success repository
  mutation is authorized.
- Do not duplicate the accepted capsule. `raw/source-manifest.json` pins its
  maintained Project Meta copy, the exact current Git tree, and the unpublished
  current-tree verification receipt.

## Canonical example

Starting from only `roadmap/codebase/wiki/index.md`, answer: “What happens when
a consumer calls `call_llm`, and where should I edit routing, retries, and
observability?” A passing answer identifies the public facade, execution plan,
retry/fallback kernel, provider route, result finalization, and durable
observability seams, with links that reopen the exact revision.

## Acceptance criteria

- The index routes architecture, workflow, concept, package, and lineage
  questions without scanning all 155 Python files.
- Every non-reserved wiki page has `type` frontmatter and source provenance.
- The capsule summary remains explicit: 155 files, 1,079 public symbols, zero
  omissions; unsupported relationships are not claimed.
- Deterministic lint reports no missing type, broken internal link, orphan, or
  index-drift finding.
- The canonical example is answered from the wiki and each exact claim is
  confirmed against source at revision `c2f3693`.
- Root `AGENTS.md` is regenerated from the canonical `CLAUDE.md` and passes its
  sync check.

## Verification

```bash
python3 "${PROJECTS_ROOT:-$HOME/code/active}/agent-skills/skills/karpathy-wiki/scripts/lint.py" roadmap/codebase/wiki
python3 scripts/meta/check_agents_sync.py --check
python3 scripts/check_markdown_links.py roadmap/codebase/wiki roadmap/README.md CLAUDE.md docs/plans/358_llm_client_karpathy_codebase_wiki.md docs/plans/CLAUDE.md
git diff --check
```

## Rollback

Revert the plan commit. The capsule and source revision remain independently
available; no runtime or remote-history transition is involved.

## Completion evidence

Completed 2026-08-16.

- The bundle contains 14 typed content pages plus `index.md` and `log.md`,
  covering all ten capsule package groups and the two critical call workflows.
- Karpathy structural lint reports `100/100` with no missing type, broken link,
  orphan, thin-page, stale-page, or index-drift finding.
- A source-reopen probe resolved the pinned current GitHub source references
  against commit `c2f3693` and checked every cited line range. The maintained
  generator was rerun after `main` advanced and confirmed 155 files, 1,079
  symbols, and zero omissions at the current tree; the accepted `f194028`
  Project Meta capsule remains separately recoverable.
- The canonical `call_llm` query resolves through the wiki to the public facade,
  call envelope, route plan, retry/fallback kernel, transport adapters, result
  finalization, and observability/budget seams. Each exact statement links to
  the pinned source.
- Generated `AGENTS.md` contains the wiki-first navigation rule and passes the
  repository sync check. Focused Markdown-link validation and `git diff
  --check` pass.
- Semantic review found no conflicting ownership or architecture claims. The
  company repository remains a separately identified downstream; present
  company revision or deployment state is explicitly not claimed.
