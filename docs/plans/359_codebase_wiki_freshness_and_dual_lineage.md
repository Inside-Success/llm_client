# Plan #359: Codebase Wiki Freshness and Dual-Lineage Ingest

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** Trustworthy ongoing wiki-first navigation across personal and company code

## Outcome

Keep the Plan 358 Karpathy-style wiki honest after source changes and make the
current Inside Success downstream inspectable as a separate, revision-bound
source. Agents should see exact differences without treating a company fork as
another name for Brian's personal repository.

## Scope

1. Add a typed deterministic checker for the personal code surface, canonical
   authority hashes, exact Project Meta capsule blobs, and optional live company
   remote pin.
2. Wire the offline source/authority check into `make check`; keep the
   credential- and network-dependent checks in an explicit full target.
3. Ingest the maintained `inside-success-llm-client` capsule and update the
   lineage page with exact ancestry and code-surface differences.
4. Preserve immutable manifests: add a new manifest and retain Plan 358's prior
   manifest as historical evidence.

## Boundaries

- Source and canonical documentation remain authoritative; the wiki and
  capsules are derived navigation.
- Personal and organization repositories retain distinct IDs, histories,
  credentials, publication authority, and deployment authority.
- The freshness checker is read-only. It does not fetch into, update, merge,
  deploy, or release either `llm_client` repository.
- A network failure is reported as unavailable; no stale remote-tracking ref is
  accepted as a substitute.

## Acceptance criteria

- The offline check passes for the current source surface and fails after a
  changed or newly tracked Python source file or changed canonical authority.
- The full check reopens both maintained capsules from exact Project Meta Git
  revisions and confirms the live company default branch remains at its pin.
- The company capsule retains `owner_class: organization`, exact remote,
  revision, tree, counts, and its 16-anchor passing receipt.
- The lineage page states the observed divergence and concrete code-surface
  delta without making a deployment or synchronization claim.
- Wiki lint, Markdown links, focused tests, typing, Ruff, AGENTS sync, and
  `git diff --check` pass.

## Verification

```bash
pytest -q tests/test_codebase_wiki_freshness.py
make codebase-wiki-check
make codebase-wiki-check-full
python3 "${PROJECTS_ROOT:-$HOME/code/active}/agent-skills/skills/karpathy-wiki/scripts/lint.py" roadmap/codebase/wiki
python3 scripts/check_markdown_links.py roadmap/codebase/wiki roadmap/README.md CLAUDE.md docs/plans/359_codebase_wiki_freshness_and_dual_lineage.md docs/plans/CLAUDE.md
python3 scripts/meta/check_agents_sync.py --check
ruff check scripts/meta/check_codebase_wiki_freshness.py tests/test_codebase_wiki_freshness.py
mypy --strict scripts/meta/check_codebase_wiki_freshness.py
git diff --check
```

## Rollback

Revert the Plan 359 commit. Project Meta retains the company capsule, and Plan
358's immutable source manifest remains available as the prior ingest.

## Completion evidence

Completed 2026-08-16.

- The offline checker passes on 156 tracked code/config files and five current
  authority documents. Focused negative tests prove that a changed source blob,
  a newly tracked Python file, or authority drift fails the check.
- The full checker reopened the personal and company capsule bytes from their
  exact Project Meta Git revisions and matched both SHA-256 pins. A live
  `ls-remote` observation matched the company default branch at `f4a08fe`.
- The company ingest retains organization ownership, revision `f4a08fe`, tree
  `feca132`, 156 modules, 1,081 public symbols, zero omissions, deterministic
  output, and a passing 16-anchor receipt.
- The lineage page records a common base at `be18982`, a diverged 7/20 commit
  relationship, and nine exact differing package paths. It makes no deployment,
  replacement, or synchronization decision.
- Four focused tests, strict mypy, focused Ruff, AGENTS sync, Markdown links,
  and `git diff --check` passed. Karpathy structural lint reports 15 pages and
  health `100/100` with no findings.
- The checker itself performs no fetch, update, merge, deployment, or release.
  The separate Project Meta publication was a recoverable personal-repository
  Git change; the actual company checkout remained byte/ref unchanged during
  its source observation.
