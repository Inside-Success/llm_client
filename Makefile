# llm_client Makefile — consumer interface for observability and development
#
# Usage: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif [ -x .venv/Scripts/python.exe ]; then echo .venv/Scripts/python.exe; else echo python; fi)
DAYS ?= 7
PROJECT ?=
LIMIT ?= 20
SURFACE ?= codebase-memory
TOOL_USAGE_CLIENT ?= both
TOOL_USAGE_DB ?=
SKIP_MALFORMED ?=

# ─── Observability ───────────────────────────────────────────────────────────

.PHONY: cost cost-by-project cost-by-model cost-by-task errors recent traces summary tool-usage-import tool-usage-report

cost:  ## Total spend (DAYS=7 default, PROJECT= optional)
	@$(PYTHON) -m llm_client cost --group-by project --days $(DAYS) \
		$(if $(PROJECT),--project $(PROJECT))

cost-by-project:  ## Spend per project (DAYS=7)
	@$(PYTHON) -m llm_client cost --group-by project --days $(DAYS)

cost-by-model:  ## Spend per model (DAYS=7, PROJECT= optional)
	@$(PYTHON) -m llm_client cost --group-by model --days $(DAYS) \
		$(if $(PROJECT),--project $(PROJECT))

cost-by-task:  ## Spend per task (DAYS=7, PROJECT= optional)
	@$(PYTHON) -m llm_client cost --group-by task --days $(DAYS) \
		$(if $(PROJECT),--project $(PROJECT))

prompt-drift:  ## Tasks whose prompt size grew past their own baseline (RECENT_DAYS/BASELINE_DAYS)
	@$(PYTHON) -m llm_client prompt-drift \
		--recent-days $(or $(RECENT_DAYS),7) \
		--baseline-days $(or $(BASELINE_DAYS),30) \
		$(if $(PROJECT),--project $(PROJECT))

errors:  ## Error breakdown by model (DAYS=7, PROJECT= optional)
	@$(PYTHON) -c "\
	import sqlite3, os; \
	from pathlib import Path; \
	db = sqlite3.connect(os.environ.get('LLM_CLIENT_DB_PATH', str(Path.home() / 'projects/data/llm_observability.db')), timeout=10); \
	from datetime import datetime, timedelta, timezone; \
	cutoff = (datetime.now(timezone.utc) - timedelta(days=$(DAYS))).isoformat(); \
	pf = \"AND project = '$(PROJECT)'\" if '$(PROJECT)' else ''; \
	rows = db.execute(f\"\"\"SELECT model, COUNT(*) as total, \
		SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors, \
		ROUND(100.0 * SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as error_pct \
		FROM llm_calls WHERE task != 'test' AND timestamp >= ? {pf} \
		GROUP BY model ORDER BY errors DESC LIMIT 20\"\"\", (cutoff,)).fetchall(); \
	print(f\"{'Model':<55} {'Total':>7} {'Errors':>7} {'Rate':>7}\"); \
	print('-' * 80); \
	[print(f'{r[0]:<55} {r[1]:>7} {r[2]:>7} {r[3]:>6}%') for r in rows]; \
	total = sum(r[1] for r in rows); errs = sum(r[2] for r in rows); \
	print('-' * 80); \
	print(f\"{'TOTAL':<55} {total:>7} {errs:>7} {(100*errs/total if total else 0):>6.1f}%\")"

recent:  ## Last N calls (LIMIT=20, PROJECT= optional)
	@$(PYTHON) -c "\
	import sqlite3, os; \
	from pathlib import Path; \
	db = sqlite3.connect(os.environ.get('LLM_CLIENT_DB_PATH', str(Path.home() / 'projects/data/llm_observability.db')), timeout=10); \
	pf = \"WHERE project = '$(PROJECT)'\" if '$(PROJECT)' else ''; \
	rows = db.execute(f\"\"\"SELECT timestamp, model, task, \
		ROUND(COALESCE(marginal_cost, cost), 4) as cost, \
		total_tokens, ROUND(latency_s, 1) as latency, \
		CASE WHEN error IS NOT NULL THEN 'ERR' ELSE 'ok' END as status \
		FROM llm_calls WHERE task != 'test' {pf} ORDER BY timestamp DESC LIMIT $(LIMIT)\"\"\").fetchall(); \
	print(f\"{'Time':<20} {'Model':<40} {'Task':<25} {'Cost':>8} {'Tokens':>8} {'Lat':>6} {'St':>4}\"); \
	print('-' * 115); \
	[print(f'{r[0][11:19]:<20} {(r[1] or \"?\")[:39]:<40} {(r[2] or \"-\")[:24]:<25} \$${ r[3] or 0:>7.4f} {r[4] or 0:>8} {r[5] or 0:>5.1f}s {r[6]:>4}') for r in rows]"

traces:  ## Recent traces with cost rollup (DAYS=3, PROJECT= optional)
	@$(PYTHON) -m llm_client traces --days $(DAYS) \
		$(if $(PROJECT),--project $(PROJECT))

summary:  ## Quick dashboard: spend, calls, errors, top models (DAYS=7)
	@echo "=== llm_client Summary (last $(DAYS) days) ==="
	@echo ""
	@$(PYTHON) -c "\
	import sqlite3, os; \
	from pathlib import Path; \
	db = sqlite3.connect(os.environ.get('LLM_CLIENT_DB_PATH', str(Path.home() / 'projects/data/llm_observability.db')), timeout=10); \
	from datetime import datetime, timedelta, timezone; \
	cutoff = (datetime.now(timezone.utc) - timedelta(days=$(DAYS))).isoformat(); \
	r = db.execute(\"\"\"SELECT COUNT(*), ROUND(COALESCE(SUM(COALESCE(marginal_cost, cost)), 0), 2), \
		SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), \
		COUNT(DISTINCT project), COUNT(DISTINCT model), \
		COALESCE(SUM(total_tokens), 0) \
		FROM llm_calls WHERE task != 'test' AND timestamp >= ?\"\"\", (cutoff,)).fetchone(); \
	print(f'  Calls:    {r[0]:,}'); \
	print(f'  Spend:    \$${r[1]:,.2f}'); \
	print(f'  Errors:   {r[2]:,} ({100*r[2]/r[0] if r[0] else 0:.1f}%)'); \
	print(f'  Projects: {r[3]}'); \
	print(f'  Models:   {r[4]}'); \
	print(f'  Tokens:   {r[5]:,}'); \
	print(); \
	print('Top projects by spend:'); \
	rows = db.execute(\"\"\"SELECT COALESCE(project,'unknown'), \
		ROUND(COALESCE(SUM(COALESCE(marginal_cost, cost)), 0), 2), COUNT(*) \
		FROM llm_calls WHERE task != 'test' AND timestamp >= ? GROUP BY project ORDER BY 2 DESC LIMIT 5\"\"\", (cutoff,)).fetchall(); \
	[print(f'  \$${r[1]:>8.2f}  {r[2]:>6} calls  {r[0]}') for r in rows]; \
	print(); \
	print('Top models by spend:'); \
	rows = db.execute(\"\"\"SELECT model, \
		ROUND(COALESCE(SUM(COALESCE(marginal_cost, cost)), 0), 2), COUNT(*) \
		FROM llm_calls WHERE task != 'test' AND timestamp >= ? GROUP BY model ORDER BY 2 DESC LIMIT 5\"\"\", (cutoff,)).fetchall(); \
	[print(f'  \$${r[1]:>8.2f}  {r[2]:>6} calls  {r[0]}') for r in rows]"

tool-usage-import:  ## Import structured agent calls (SURFACE=codebase-memory)
	@$(PYTHON) -m llm_client tool-usage import --surface "$(SURFACE)" \
		--client "$(TOOL_USAGE_CLIENT)" \
		$(if $(TOOL_USAGE_DB),--db "$(TOOL_USAGE_DB)") \
		$(if $(SKIP_MALFORMED),--skip-malformed-files)

tool-usage-report:  ## Report agent tool usage (SURFACE=codebase-memory)
	@$(PYTHON) -m llm_client tool-usage report --surface "$(SURFACE)" \
		$(if $(TOOL_USAGE_DB),--db "$(TOOL_USAGE_DB)")

# ─── Development ─────────────────────────────────────────────────────────────

.PHONY: test test-verbose test-integration lint typecheck check install dead-code dead-code-audit dead-code-validate codebase-wiki-check codebase-wiki-check-full reachability reachability-check reachability-baseline repo-stats

test:  ## Run all tests
	python -m pytest tests/ -q

test-quick:  ## Run tests (minimal output)
	python -m pytest tests/ -q --tb=no

test-verbose:  ## Run tests with verbose output
	python -m pytest tests/ -v

test-integration:  ## Run integration tests (requires LLM_CLIENT_INTEGRATION=1)
	LLM_CLIENT_INTEGRATION=1 python -m pytest tests/ -v -m integration

lint:  ## Run ruff linter
	ruff check llm_client/ tests/

typecheck:  ## Run mypy type checking
	mypy --strict llm_client/

codebase-wiki-check:  ## Fail when the compiled codebase wiki is stale
	@$(PYTHON) scripts/meta/check_codebase_wiki_freshness.py

codebase-wiki-check-full:  ## Also authenticate Project Meta capsules and company remote state
	@$(PYTHON) scripts/meta/check_codebase_wiki_freshness.py \
		--external-repository "project-meta=$${PROJECTS_ROOT:-$$HOME/code/active}/project-meta" \
		--require-external --network

check: codebase-wiki-check lint typecheck test  ## Run all quality checks

install:  ## Install in editable mode with dev deps
	$(PYTHON) -m pip install -e ".[dev]"

dead-code:  ## Run dead code detection
	@$(PYTHON) scripts/meta/check_dead_code.py

dead-code-audit:  ## Refresh reviewed dead-code audit file
	@$(PYTHON) scripts/meta/audit_dead_code.py --write

dead-code-validate:  ## Validate reviewed dead-code dispositions
	@$(PYTHON) scripts/meta/validate_dead_code_audit.py

reachability:  ## Report module reachability across llm_client/scripts/tests/enforced_planning
	@$(PYTHON) scripts/meta/check_reachability.py --project-root .

reachability-check:  ## Fail if any module became unreachable since the baseline
	@$(PYTHON) scripts/meta/check_reachability.py --project-root . --check

reachability-baseline:  ## Lower the ratchet after retiring modules
	@$(PYTHON) scripts/meta/check_reachability.py --project-root . --write-baseline

repo-stats:  ## Print repetition counters for session start
	@$(PYTHON) scripts/meta/repo_stats_block.py --project-root .

# ─── Maintenance ─────────────────────────────────────────────────────────────

.PHONY: api-docs models log-stats log-rotate log-cleanup

api-docs:  ## Regenerate API reference docs
	@$(PYTHON) scripts/meta/generate_api_reference.py --write

models:  ## Show model registry
	@$(PYTHON) -m llm_client models

log-stats:  ## Show JSONL log sizes per project
	@$(PYTHON) scripts/log_maintenance.py stats

log-rotate:  ## Rotate oversized JSONL logs (MAX_SIZE_MB=100, DRY_RUN= for preview)
	@$(PYTHON) scripts/log_maintenance.py rotate \
		--max-size $(or $(MAX_SIZE_MB),100) \
		$(if $(DRY_RUN),--dry-run)

log-cleanup:  ## Archive old JSONL logs (ARCHIVE_DAYS=90, DELETE_DAYS= optional, DRY_RUN= for preview)
	@$(PYTHON) scripts/log_maintenance.py cleanup \
		--days $(or $(ARCHIVE_DAYS),90) \
		$(if $(DELETE_DAYS),--delete-days $(DELETE_DAYS)) \
		$(if $(DRY_RUN),--dry-run)

# ─── Workbench ───────────────────────────────────────────────────────────────

.PHONY: workbench-backend workbench-frontend workbench-install

workbench-backend:  ## Start observability workbench backend (:5203)
	cd workbench/backend && $(PYTHON) -m uvicorn server:app --host 0.0.0.0 --port 5203 --reload

workbench-frontend:  ## Start observability workbench frontend (:5204)
	cd workbench/frontend && npm run dev

workbench-install:  ## Install workbench backend deps
	$(PYTHON) -m pip install fastapi "uvicorn[standard]" --quiet

# ─── Help ────────────────────────────────────────────────────────────────────

.PHONY: help

help:  ## Show all targets
	@echo "llm_client — runtime substrate for multi-provider LLM calls"
	@echo ""
	@echo "Development:"
	@grep -E '^[a-z].*:.*## ' $(MAKEFILE_LIST) | grep -E '^(test|lint|typecheck|check|install|dead-code|dead-code-audit|dead-code-validate)' | \
		awk -F ':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Observability:"
	@grep -E '^[a-z].*:.*## ' $(MAKEFILE_LIST) | grep -E '^(cost|errors|recent|traces|summary|tool-usage)' | \
		awk -F ':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Maintenance:"
	@grep -E '^[a-z].*:.*## ' $(MAKEFILE_LIST) | grep -E '^(api-docs|models|log-)' | \
		awk -F ':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Worktrees:"
	@grep -E '^[a-z].*:.*## ' $(MAKEFILE_LIST) | grep -E '^(worktree|worktree-list|worktree-remove)' | \
		awk -F ':.*## ' '{printf "  make %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Options: DAYS=7 PROJECT= LIMIT=20 SURFACE=codebase-memory TOOL_USAGE_CLIENT=both TOOL_USAGE_DB= SKIP_MALFORMED= MAX_SIZE_MB=100 ARCHIVE_DAYS=90 DRY_RUN= DELETE_DAYS="

# >>> META-PROCESS WORKTREE TARGETS >>>
WORKTREE_CREATE_SCRIPT := scripts/meta/worktree-coordination/create_worktree.py
WORKTREE_REMOVE_SCRIPT := scripts/meta/worktree-coordination/safe_worktree_remove.py
WORKTREE_CLAIMS_SCRIPT := scripts/meta/worktree-coordination/../check_coordination_claims.py
WORKTREE_SESSION_START_SCRIPT := scripts/meta/worktree-coordination/../session_start.py
WORKTREE_SESSION_HEARTBEAT_SCRIPT := scripts/meta/worktree-coordination/../session_heartbeat.py
WORKTREE_SESSION_STATUS_SCRIPT := scripts/meta/worktree-coordination/../session_status.py
WORKTREE_SESSION_END_SCRIPT := scripts/meta/worktree-coordination/../session_end.py
WORKTREE_SESSION_FINISH_SCRIPT := scripts/meta/worktree-coordination/../session_finish.py
WORKTREE_SESSION_CLOSE_SCRIPT := scripts/meta/worktree-coordination/../session_close.py
WORKTREE_REVIEW_CLAIM_SCRIPT := scripts/meta/worktree-coordination/create_review_claim.py
WORKTREE_RAISE_CONCERN_SCRIPT := scripts/meta/worktree-coordination/raise_concern.py
WORKTREE_PLAN_READINESS_SCRIPT := scripts/meta/worktree-coordination/../check_plan_readiness.py
WORKTREE_DIR ?= $(shell python "$(WORKTREE_CREATE_SCRIPT)" --repo-root . --print-default-worktree-dir)
WORKTREE_START_POINT ?= HEAD
WORKTREE_PROJECT ?= $(shell python "$(WORKTREE_CREATE_SCRIPT)" --repo-root . --print-canonical-project)
WORKTREE_AGENT ?= $(shell if [ -n "$$CODEX_THREAD_ID" ]; then printf codex; elif [ -n "$$CLAUDE_SESSION_ID" ] || [ -n "$$CLAUDE_CODE_SSE_PORT" ]; then printf claude-code; elif [ -n "$$OPENCLAW_SESSION_ID" ] || [ -n "$$OPENCLAW_RUN_ID" ]; then printf openclaw; fi)
SESSION_GOAL ?=
SESSION_PHASE ?=
SESSION_NEXT ?=
SESSION_DEPENDS ?=
SESSION_STOP_CONDITIONS ?=
SESSION_NOTE ?=
SESSION_ALLOW_PARALLEL ?=
ALLOW_UNPLANNED ?=
PLAN_RESUME ?=
WORKTREE_EXECUTION_PROFILE ?= coordinated
PLAN_PROJECT ?= $(WORKTREE_PROJECT)
PLAN_READINESS_COMMAND ?=
SESSION_CLAIM_TYPE ?= program
SESSION_PARENT_SCOPE ?=
SESSION_WRITE_PATHS ?=
SESSION_READ_PATHS ?=
WORKTREE_DISPOSITION ?= merged
WORKTREE_DISPOSITION_REASON ?=
WORKTREE_RECOVERY_REF ?=
WORKTREE_ALLOW_DISCARD_UNIQUE ?=
WORKTREE_MERGE_COMMIT ?=
REVIEW_SCOPE ?=
REVIEW_NOTES ?=
RECIPIENT ?=

.PHONY: worktree maintenance-worktree worktree-list worktree-remove session-start session-heartbeat session-status session-end session-finish session-close review-claim raise-concern verification-batch-freeze verification-batch-check verification-batch-thaw

verification-batch-freeze:  ## Freeze clean HEAD for DECISION="..." VERIFY_COMMAND="..."
	@test -n "$(DECISION)" || (echo "DECISION is required" && exit 1)
	@test -n "$(VERIFY_COMMAND)" || (echo "VERIFY_COMMAND is required" && exit 1)
	$(PYTHON) scripts/meta/verification_batch.py --repo-root . freeze --decision "$(DECISION)" --command "$(VERIFY_COMMAND)" $(if $(ALLOW_UNTRACKED),--allow-untracked "$(ALLOW_UNTRACKED)",)

verification-batch-check:  ## Require the active batch to match exact clean HEAD
	$(PYTHON) scripts/meta/verification_batch.py --repo-root . check --require-active

verification-batch-thaw:  ## Invalidate the batch with REASON="..." before a scoped fix
	@test -n "$(REASON)" || (echo "REASON is required" && exit 1)
	$(PYTHON) scripts/meta/verification_batch.py --repo-root . thaw --reason "$(REASON)"

worktree:  ## Create claimed worktree (BRANCH=name TASK="..." [PLAN=N] [AGENT=name])
ifndef BRANCH
	$(error BRANCH is required. Usage: make worktree BRANCH=plan-42-feature TASK="Describe the task")
endif
ifndef TASK
	$(error TASK is required. Usage: make worktree BRANCH=plan-42-feature TASK="Describe the task")
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader objective, not the local branch)
endif
ifndef SESSION_PHASE
	$(error SESSION_PHASE is required. Describe the current execution phase)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@if [ ! -f "$(WORKTREE_CREATE_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CREATE_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree."; \
		exit 1; \
	fi
	@if [ ! -f "$(WORKTREE_CLAIMS_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CLAIMS_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree."; \
		exit 1; \
	fi
	@if [ ! -f "$(WORKTREE_SESSION_START_SCRIPT)" ]; then \
		echo "Missing session lifecycle module: $(WORKTREE_SESSION_START_SCRIPT)"; \
		echo "Install or sync the sanctioned session lifecycle module before using make worktree."; \
		exit 1; \
	fi
	@python "$(WORKTREE_PLAN_READINESS_SCRIPT)" \
		$(if $(PLAN),--qualified-plan-id "$(PLAN_PROJECT)#$(PLAN)",) \
		--execution-profile "$(WORKTREE_EXECUTION_PROFILE)" \
		$(if $(PLAN_READINESS_COMMAND),--query-command "$(PLAN_READINESS_COMMAND)",) \
		--repository "$(WORKTREE_PROJECT)" \
		--lane-id "$(BRANCH)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-lane-id "$(SESSION_PARENT_SCOPE)",) \
		--branch "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--agent "$(WORKTREE_AGENT)" \
		--scope "$(BRANCH)" \
		$(if $(ALLOW_UNPLANNED),--allow-unplanned,) \
		$(if $(PLAN_RESUME),--resume,)
	@python "$(WORKTREE_CLAIMS_SCRIPT)" --claim \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		--branch "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--session-name "$(SESSION_GOAL)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",)
	@mkdir -p "$(WORKTREE_DIR)"
	@if ! python "$(WORKTREE_CREATE_SCRIPT)" --repo-root . --path "$(WORKTREE_DIR)/$(BRANCH)" --branch "$(BRANCH)" --start-point "$(WORKTREE_START_POINT)"; then \
		python "$(WORKTREE_CLAIMS_SCRIPT)" --release --agent "$(WORKTREE_AGENT)" --project "$(WORKTREE_PROJECT)" --scope "$(BRANCH)" >/dev/null 2>&1 || true; \
		exit 1; \
	fi
	@if ! python "$(WORKTREE_SESSION_START_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--repo-root "$(CURDIR)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--broader-goal "$(SESSION_GOAL)" \
		--current-phase "$(SESSION_PHASE)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",) \
		$(if $(ALLOW_UNPLANNED),--allow-unplanned,) \
		$(if $(SESSION_NEXT),--next-phase "$(SESSION_NEXT)",) \
		$(if $(SESSION_DEPENDS),--depends-on "$(SESSION_DEPENDS)",) \
		$(if $(SESSION_STOP_CONDITIONS),--stop-condition "$(SESSION_STOP_CONDITIONS)",) \
		$(if $(SESSION_NOTE),--notes "$(SESSION_NOTE)",); then \
		git worktree remove --force "$(WORKTREE_DIR)/$(BRANCH)" >/dev/null 2>&1 || true; \
		git branch -D "$(BRANCH)" >/dev/null 2>&1 || true; \
		python "$(WORKTREE_CLAIMS_SCRIPT)" --release --agent "$(WORKTREE_AGENT)" --project "$(WORKTREE_PROJECT)" --scope "$(BRANCH)" >/dev/null 2>&1 || true; \
		exit 1; \
	fi
	@echo ""
	@echo "Worktree created at $(WORKTREE_DIR)/$(BRANCH)"
	@echo "Claim created for branch $(BRANCH)"
	@echo "Session contract started for $(SESSION_GOAL)"

maintenance-worktree:  ## Create a claimed light maintenance worktree without a numbered plan
	@if [ -n "$(PLAN)" ]; then \
		echo "maintenance-worktree is only for explicitly unplanned light maintenance; use make worktree PLAN=N for plan-owned work."; \
		exit 2; \
	fi
	@$(MAKE) worktree \
		BRANCH="$(BRANCH)" TASK="$(TASK)" WORKTREE_AGENT="$(WORKTREE_AGENT)" \
		SESSION_GOAL="$(SESSION_GOAL)" SESSION_PHASE="$(SESSION_PHASE)" \
		SESSION_NEXT="$(SESSION_NEXT)" SESSION_DEPENDS="$(SESSION_DEPENDS)" \
		SESSION_STOP_CONDITIONS="$(SESSION_STOP_CONDITIONS)" SESSION_NOTE="$(SESSION_NOTE)" \
		SESSION_CLAIM_TYPE="$(SESSION_CLAIM_TYPE)" SESSION_PARENT_SCOPE="$(SESSION_PARENT_SCOPE)" \
		SESSION_ALLOW_PARALLEL="$(SESSION_ALLOW_PARALLEL)" \
		SESSION_WRITE_PATHS="$(SESSION_WRITE_PATHS)" SESSION_READ_PATHS="$(SESSION_READ_PATHS)" \
		WORKTREE_EXECUTION_PROFILE=light ALLOW_UNPLANNED=1

session-start:  ## Create or refresh the active session contract for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-start BRANCH=plan-42-feature TASK="..." SESSION_GOAL="..." SESSION_PHASE="...")
endif
ifndef TASK
	$(error TASK is required. Usage: make session-start BRANCH=plan-42-feature TASK="...")
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader objective, not the local branch)
endif
ifndef SESSION_PHASE
	$(error SESSION_PHASE is required. Describe the current execution phase)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_SESSION_START_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--repo-root "$(CURDIR)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--broader-goal "$(SESSION_GOAL)" \
		--current-phase "$(SESSION_PHASE)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(PLAN),--plan "Plan #$(PLAN)",) \
		$(if $(ALLOW_UNPLANNED),--allow-unplanned,) \
		$(if $(SESSION_NEXT),--next-phase "$(SESSION_NEXT)",) \
		$(if $(SESSION_DEPENDS),--depends-on "$(SESSION_DEPENDS)",) \
		$(if $(SESSION_STOP_CONDITIONS),--stop-condition "$(SESSION_STOP_CONDITIONS)",) \
		$(if $(SESSION_NOTE),--notes "$(SESSION_NOTE)",)

session-heartbeat:  ## Refresh heartbeat and optional phase for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-heartbeat BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_SESSION_HEARTBEAT_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--branch "$(BRANCH)" \
		$(if $(SESSION_PHASE),--current-phase "$(SESSION_PHASE)",)

session-status:  ## Show live session summaries for this repo
	@python "$(WORKTREE_SESSION_STATUS_SCRIPT)" --project "$(WORKTREE_PROJECT)"

session-end:  ## Retire this runtime session's live claims without deleting Git work
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_SESSION_END_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		$(if $(SESSION_NOTE),--reason "$(SESSION_NOTE)",)

session-finish:  ## Finish the session for BRANCH=name; blocks if the worktree is dirty
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-finish BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_SESSION_FINISH_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		$(if $(SESSION_NOTE),--note "$(SESSION_NOTE)",)

session-close:  ## Close the claimed lane for BRANCH=name: cleanup worktree + branch + claim together
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-close BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_SESSION_CLOSE_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--disposition "$(WORKTREE_DISPOSITION)" \
		--disposition-reason "$(WORKTREE_DISPOSITION_REASON)" \
		--recovery-ref "$(WORKTREE_RECOVERY_REF)" \
		$(if $(filter 1 true yes,$(WORKTREE_ALLOW_DISCARD_UNIQUE)),--allow-discard-unique,) \
		$(if $(WORKTREE_MERGE_COMMIT),--merge-commit "$(WORKTREE_MERGE_COMMIT)",) \
		$(if $(SESSION_NOTE),--note "$(SESSION_NOTE)",)

worktree-list:  ## Show claimed worktree coordination status
	@if [ ! -f "$(WORKTREE_CLAIMS_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CLAIMS_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree-list."; \
		exit 1; \
	fi
	@python "$(WORKTREE_CLAIMS_SCRIPT)" --list

worktree-remove:  ## Safely remove worktree for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make worktree-remove BRANCH=plan-42-feature)
endif
	@if [ ! -f "$(WORKTREE_SESSION_CLOSE_SCRIPT)" ]; then \
		echo "Missing session lifecycle module: $(WORKTREE_SESSION_CLOSE_SCRIPT)"; \
		echo "Install or sync the sanctioned session lifecycle module before using make worktree-remove."; \
		exit 1; \
	fi
	@$(MAKE) session-close BRANCH="$(BRANCH)" \
		$(if $(WORKTREE_MERGE_COMMIT),WORKTREE_MERGE_COMMIT="$(WORKTREE_MERGE_COMMIT)",) \
		$(if $(SESSION_NOTE),SESSION_NOTE="$(SESSION_NOTE)",)

review-claim:  ## Create a review claim for TARGET_BRANCH=name WRITE_PATHS="a|b" TASK="..."
ifndef TARGET_BRANCH
	$(error TARGET_BRANCH is required. Usage: make review-claim TARGET_BRANCH=plan-42-feature WRITE_PATHS="src/foo.py|tests/test_foo.py" TASK="Review concern")
endif
ifndef WRITE_PATHS
	$(error WRITE_PATHS is required. Provide one or more repo-relative paths separated by '|')
endif
ifndef TASK
	$(error TASK is required. Describe the review intent)
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader review objective)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@python "$(WORKTREE_REVIEW_CLAIM_SCRIPT)" \
		--repo-root "$(CURDIR)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--target-branch "$(TARGET_BRANCH)" \
		--intent "$(TASK)" \
		--session-name "$(SESSION_GOAL)" \
		--write-path "$(WRITE_PATHS)" \
		$(if $(PLAN),--plan "Plan #$(PLAN)",) \
		$(if $(REVIEW_SCOPE),--scope "$(REVIEW_SCOPE)",) \
		$(if $(REVIEW_NOTES),--notes "$(REVIEW_NOTES)",)

raise-concern:  ## Route concern to TARGET_BRANCH via PR comment or local inbox
ifndef TARGET_BRANCH
	$(error TARGET_BRANCH is required. Usage: make raise-concern TARGET_BRANCH=plan-42-feature SUBJECT="..." MESSAGE="...")
endif
ifndef SUBJECT
	$(error SUBJECT is required. Usage: make raise-concern TARGET_BRANCH=plan-42-feature SUBJECT="..." MESSAGE="...")
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
ifndef MESSAGE
ifndef MESSAGE_FILE
	$(error MESSAGE or MESSAGE_FILE is required. Provide inline content or a path to a concern file)
endif
endif
	@python "$(WORKTREE_RAISE_CONCERN_SCRIPT)" \
		--repo-root "$(CURDIR)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--target-branch "$(TARGET_BRANCH)" \
		--subject "$(SUBJECT)" \
		$(if $(MESSAGE),--content "$(MESSAGE)",) \
		$(if $(MESSAGE_FILE),--content-file "$(MESSAGE_FILE)",) \
		$(if $(RECIPIENT),--recipient "$(RECIPIENT)",)
# <<< META-PROCESS WORKTREE TARGETS <<<

PROJECT_STATUS_PYTHON ?= $(if $(strip $(PYTHON)),$(PYTHON),$(if $(wildcard .venv/bin/python),.venv/bin/python,python3))
PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py
status:  ## Verify repository authority freshness and show branch status
	@$(PROJECT_STATUS_PYTHON) $(PROJECT_STATUS_SCRIPT) --repo-root .
