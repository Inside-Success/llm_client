"""Deliberation workflow: symmetric N-agent debate as a sibling to the duet.

Where the duet is asymmetric (one implementer + one gating reviewer + 1 revise
cycle), deliberation is symmetric: both agents get the same task brief and
workspace, each writes its own ``Position`` (claims + evidence + open
questions), they exchange positions, and they iterate until a rule-based
convergence detector fires or the round cap is hit.

Topology (two-agent v1):
  round 1: agent_a writes initial position → agent_b writes initial position
  round 2: agent_a reads agent_b's prior + own prior, writes revised position
           → agent_b reads agent_a's latest + own prior, writes revised
  ...
  convergence_check after each round:
    - converged: both latest positions have empty ``disagreed_with_peer``
      AND ``round >= 2`` AND each agent's ``agreed_with_peer`` covers the
      peer's claim IDs.
    - productive_disagreement: round cap reached with residual
      ``disagreed_with_peer`` on either side.
    - stalled: both agents emit empty positions.
  synthesis: third LLM call (or one of the agents) merges findings + lists
  residual disagreements. Persisted to ``synthesis.json``.

Shares chassis with the duet:
- ``TaskFamily`` registry (Plan #31) — deliberation can also be specialized
  by profile when domain-specific Position fields are needed.
- Grounded schemas — ``PositionClaim.evidence_path`` and
  ``DisagreementAtom.evidence_path`` are required (Plan #30 contract).
- ``WorkflowContext`` for trace/budget/observability.
- Model alias resolution (Plan #29 followup) + cwd↔working_directory alias
  (Plan #30 followup).

See ``docs/plans/33_deliberation_workflow.md`` for the design rationale.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from llm_client.workflow.config import WorkflowConfig
from llm_client.workflow.context import WorkflowContext
from llm_client.workflow.deliberate_verifier import (
    LedgerEntry,
    VerifierLedger,
    verify_round,
)

logger = logging.getLogger(__name__)


DeliberationVerdict = Literal["converged", "productive_disagreement", "stalled"]
PositionState = Literal["initial", "revised", "stable"]
Confidence = Literal["low", "medium", "high"]
ClaimSeverity = Literal["info", "warn", "high"]


# Default two-agent pair — codex implements/explores, claude-code structures.
# Operators with strong opinions about model choice override via ``agents=``
# at builder time or ``--agents`` at the CLI.
DEFAULT_AGENT_PAIR: tuple[tuple[str, str], tuple[str, str]] = (
    ("agent_a", "codex/gpt-5.4"),
    ("agent_b", "claude-code/opus"),
)

# Stage timeouts mirror the duet defaults — agent calls take minutes when
# they explore the workspace.
DEFAULT_DELIBERATION_STAGE_TIMEOUT_S = 300
DEFAULT_DELIBERATION_CODEX_TRANSPORT = "auto"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DeliberationTask(BaseModel):
    """The task or question two (or more) agents are asked to deliberate on.

    Reframed vs ``DuetTask``: there is no "plan to implement", just a
    ``question`` and the constraints/criteria the agents should hold each
    other to. ``extra`` mirrors ``DuetTask.extra`` so domain profiles
    (twin debates, eval audits) can stash per-task params.
    """

    task_id: str
    title: str
    question: str
    workspace_path: str
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class PositionClaim(BaseModel):
    """One atomic claim an agent makes in its position.

    ``claim_id`` lets the peer agent reference this claim by ID in
    ``agreed_with_peer`` / ``disagreed_with_peer``. ``evidence_path`` is
    required — a claim without a citation is opinion, not evidence (same
    groundedness contract as duet's ``PlanReviewBlocker``).
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim: str
    severity: ClaimSeverity = "warn"
    evidence_path: str


class PositionEvidence(BaseModel):
    """A piece of evidence the agent pulled into its position.

    Agents cite explicit evidence so the peer can scrutinize the source
    rather than just the claim. ``content_snippet`` is the actual text the
    agent saw — required for falsifiability.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    citation: str
    content_snippet: str


class DisagreementAtom(BaseModel):
    """A specific disagreement with one of the peer's claims.

    Required ``evidence_path`` keeps disagreement falsifiable — an agent
    can't just say "I disagree" without citing why.
    """

    model_config = ConfigDict(extra="forbid")

    peer_claim_id: str
    my_counterclaim: str
    evidence_path: str


class Position(BaseModel):
    """One agent's stance at one round of the deliberation.

    Persisted to ``<run_dir>/position_<agent>_round_<N>.json``. Used as
    input to the peer's next round.
    """

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    round: int
    claims: list[PositionClaim] = Field(default_factory=list)
    evidence: list[PositionEvidence] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    agreed_with_peer: list[str] = Field(default_factory=list)
    disagreed_with_peer: list[DisagreementAtom] = Field(default_factory=list)
    confidence: Confidence = "medium"
    state: PositionState = "initial"
    reviewer_summary: str = ""
    reviewer_model: str = ""


class DeliberationSignoff(BaseModel):
    """Terminal record of a deliberation run.

    Persisted to ``<run_dir>/signoff.json`` at the workflow's terminal node.
    """

    task_id: str
    final_verdict: DeliberationVerdict
    total_rounds: int
    agents: list[str]
    residual_disagreements: list[DisagreementAtom] = Field(default_factory=list)
    trace_id: str
    artifacts_index: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# State + config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliberationAgent:
    """One agent participating in the deliberation."""

    name: str
    model: str


class DeliberationState(TypedDict, total=False):
    """LangGraph state for the deliberation workflow."""

    task: dict[str, Any]
    run_dir: str
    round: int
    max_rounds: int
    agents: list[dict[str, str]]  # serialized DeliberationAgent records
    # Latest position per agent, keyed by agent name.
    latest_positions: dict[str, dict[str, Any]]
    # Previous round's positions per agent, used by the verifier for lineage.
    prior_positions_by_agent: dict[str, dict[str, Any]]
    # Full history: list of position dicts in chronological order.
    position_history: list[dict[str, Any]]
    # Per-round verifier ledger (Plan #34). Serialized form: list of entry dicts.
    verifier_ledger: list[dict[str, Any]]
    final_verdict: DeliberationVerdict
    error: str
    # WorkflowContext fields
    _wf_trace_id: str
    _wf_max_budget: float
    _wf_task_prefix: str
    _wf_current_stage: str


# ---------------------------------------------------------------------------
# Convergence detector (pure-Python, no LLM call)
# ---------------------------------------------------------------------------


def detect_convergence(
    latest_positions: dict[str, dict[str, Any]],
    round_num: int,
    max_rounds: int,
    ledger: VerifierLedger | None = None,
) -> DeliberationVerdict | None:
    """Decide whether deliberation has reached a terminal state.

    When ``ledger`` is provided (Plan #34): refuse to fire ``"converged"`` if
    the latest round has any unverified ledger entry OR any lineage flag
    (silent rename / silent retire / fabricated peer reference). This makes
    the convergence verdict depend on resolved evidence rather than
    agents' self-reported ``agreed_with_peer`` / ``disagreed_with_peer``.

    When ``ledger`` is ``None``: preserves the pre-Plan-#34 behavior so
    callers that haven't migrated still work.

    Returns:
        ``"converged"`` if round >= 2 and every agent's latest position has
        an empty ``disagreed_with_peer`` AND covers every claim ID the peer
        last emitted in ``agreed_with_peer`` AND (when ledger supplied) the
        latest round has no unverified entries or lineage flags.

        ``"stalled"`` if every agent's latest position has zero claims (i.e.
        both agents failed to engage).

        ``"productive_disagreement"`` if ``round >= max_rounds`` and at
        least one agent still has a non-empty ``disagreed_with_peer``.

        ``None`` if deliberation should continue (no terminal state reached).
    """
    if not latest_positions:
        return None

    # Stalled: every agent emitted zero claims.
    if all(not pos.get("claims") for pos in latest_positions.values()):
        return "stalled"

    if round_num < 2:
        # Need at least one cross-agent exchange before convergence can fire.
        # Don't terminate yet unless we already detected stalled above.
        return None

    # Build a quick map of {agent_name: position} for cross-referencing.
    names = list(latest_positions)
    if len(names) < 2:
        # Single-agent deliberation makes no sense; treat as stalled.
        return "stalled"

    converged_signal = True
    for agent_name, pos in latest_positions.items():
        if pos.get("disagreed_with_peer"):
            converged_signal = False
            break
        # Check that this agent acknowledged each peer's claims.
        agreed_set = set(pos.get("agreed_with_peer") or [])
        for other_name, other_pos in latest_positions.items():
            if other_name == agent_name:
                continue
            other_claim_ids = {
                c.get("claim_id") for c in (other_pos.get("claims") or []) if c.get("claim_id")
            }
            if not other_claim_ids.issubset(agreed_set):
                converged_signal = False
                break
        if not converged_signal:
            break

    if converged_signal:
        # Plan #34: when a ledger is provided, also require that the latest
        # round in the ledger has no unverified citations or lineage flags.
        # The ledger's round numbers track position.round (not the router's
        # state["round"] which is one ahead of the latest position), so look
        # up the latest round from the ledger itself.
        if ledger is not None:
            latest_round = ledger.latest_round()
            if latest_round is not None:
                if (
                    ledger.has_unverified_in_round(latest_round)
                    or ledger.has_lineage_flag_in_round(latest_round)
                ):
                    converged_signal = False

    if converged_signal:
        return "converged"

    if round_num >= max_rounds:
        return "productive_disagreement"

    return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _task_brief(task: dict[str, Any]) -> str:
    lines = [
        f"task_id: {task.get('task_id', '?')}",
        f"title: {task.get('title', '?')}",
        f"question: {task.get('question', '?')}",
        f"workspace_path: {task.get('workspace_path', '?')}",
    ]
    if task.get("success_criteria"):
        lines.append("success_criteria:")
        lines.extend(f"  - {c}" for c in task["success_criteria"])
    if task.get("constraints"):
        lines.append("constraints:")
        lines.extend(f"  - {c}" for c in task["constraints"])
    return "\n".join(lines)


def _anonymize_peer_for_prompt(peer_latest: dict[str, Any]) -> dict[str, Any]:
    """Plan #35 Phase 2: strip peer identity fields before serializing into
    the agent's prompt.

    Replaces the peer's ``agent_name`` (e.g. ``"agent_a"``) with the neutral
    label ``"peer"`` and clears ``reviewer_model`` (which would otherwise leak
    the underlying model identity like ``"claude-code/opus"`` /
    ``"codex/gpt-5.4"``). The arXiv:2510.07517 result (Identity Bias in
    Multi-Agent Debate, 2025) shows prompt-level anonymization drops the
    conformity-obstinacy gap from 0.608 to 0.024 on MMLU; this is the cheapest
    bias-reduction intervention available.

    All other fields — claims, evidence, claim_ids, agreed_with_peer,
    disagreed_with_peer — are preserved because the convergence detector and
    verifier ledger key on claim_id, not on speaker identity.
    """
    anonymized = dict(peer_latest)
    anonymized["agent_name"] = "peer"
    anonymized["reviewer_model"] = ""
    return anonymized


def _position_prompt(
    task: dict[str, Any],
    agent_name: str,
    round_num: int,
    own_prior: dict[str, Any] | None,
    peer_latest: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build the prompt for one agent's turn at one round."""
    system = (
        "You are one of two coding agents in a structured deliberation. The other "
        "agent is investigating the same question independently. Your output is "
        "consumed by an automatic convergence detector, so it MUST validate against "
        "the Position schema. Groundedness rule: every claim and every "
        "disagreement must include an evidence_path citation (file:line, file path, "
        "or doc#section). If you cannot cite a source, downgrade to an "
        "open_question instead of asserting a claim."
    )

    user_parts = [
        "## Task",
        _task_brief(task),
        "",
        f"## Your role: {agent_name} (round {round_num})",
    ]

    if peer_latest:
        user_parts.extend([
            "",
            "## Peer's most-recent position",
            "Reference peer claims by their claim_id when acknowledging or disagreeing.",
            "",
            json.dumps(_anonymize_peer_for_prompt(peer_latest), indent=2),
        ])
    else:
        user_parts.extend([
            "",
            "## Peer position",
            "None yet — this is round 1. Investigate the task independently. "
            "Do not speculate about what the other agent will say.",
        ])

    if own_prior:
        user_parts.extend([
            "",
            "## Your prior position (last round)",
            "Revise where your view changed after seeing the peer's input. Keep claims you still hold.",
            "",
            json.dumps(own_prior, indent=2),
        ])

    user_parts.extend([
        "",
        "## Schema for your response (Position)",
        json.dumps(Position.model_json_schema(), indent=2),
        "",
        f"Return a Position JSON object with agent_name='{agent_name}' and round={round_num}. "
        "Use 'initial' state on round 1, 'revised' when you changed your view, 'stable' when "
        "your view didn't change but you acknowledge peer claims.",
    ])

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _synthesis_prompt(
    task: dict[str, Any],
    positions: list[dict[str, Any]],
    verdict: DeliberationVerdict,
) -> list[dict[str, Any]]:
    """Build the prompt for the synthesis stage."""
    system = (
        "You are synthesizing a structured deliberation between two agents. "
        "Produce a final synthesis that merges what the agents agreed on and "
        "explicitly lists what they could not agree on. Do not pick a winner "
        "unless the residual disagreements are entirely ungrounded — surface "
        "real disagreements rather than papering over them."
    )
    user_parts = [
        "## Task",
        _task_brief(task),
        "",
        f"## Final verdict: {verdict}",
        "",
        "## Position history (chronological)",
        json.dumps(positions, indent=2),
        "",
        "Return a synthesis with:",
        "- A short merged-findings narrative.",
        "- An explicit list of residual_disagreements (peer_claim_id, my_counterclaim, evidence_path).",
        "- Any open_questions that neither agent resolved.",
    ]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Artifact persistence
# ---------------------------------------------------------------------------


def _persist_json(run_dir: str, name: str, payload: dict[str, Any]) -> str:
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def _make_agent_position_node(
    agent: DeliberationAgent,
    peer_name: str,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a node that produces this agent's position for the current round.

    The node reads the task, the peer's latest position (if any), and this
    agent's own prior position (if any) from state. Emits a new Position
    via ``ctx.call_llm_structured``. Persists to disk and updates state.
    """

    def position_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage=f"deliberate.{agent.name}")
        task = state["task"]
        round_num = state["round"]
        latest = state.get("latest_positions") or {}
        own_prior = latest.get(agent.name)
        # Plan #35: read peer state from the round-(N-1) snapshot, not from
        # latest_positions. This is the Within-Round barrier protocol — the
        # cascade `agent_a → agent_b → verifier` would otherwise let agent_b
        # see agent_a's freshest round-N output (same-round second-mover
        # advantage). The verifier publishes prior_positions_by_agent at the
        # end of every round, so on round N this dict contains round-(N-1)
        # positions for both agents. Round 1: the dict is empty, which
        # matches the "no peer state yet" semantics already documented in
        # _position_prompt. Citations: Du et al. (arXiv:2305.14325);
        # 2026 controlled study (arXiv:2603.28813); see Plan #35.
        prior_by_agent = state.get("prior_positions_by_agent") or {}
        peer_latest = prior_by_agent.get(peer_name)

        messages = _position_prompt(
            task,
            agent.name,
            round_num,
            own_prior=own_prior,
            peer_latest=peer_latest,
        )
        position, _meta = ctx.call_llm_structured(
            agent.model,
            messages,
            Position,
            timeout=DEFAULT_DELIBERATION_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DELIBERATION_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        payload = position.model_dump()
        # Overwrite reviewer_model with the requested model — the LLM
        # sometimes self-reports a free-text vibe (caught in duet runs).
        payload["reviewer_model"] = agent.model
        # Force agent_name and round to match what the chassis asked for
        # rather than trusting the LLM's self-report.
        payload["agent_name"] = agent.name
        payload["round"] = round_num

        _persist_json(
            state["run_dir"],
            f"position_{agent.name}_round_{round_num}.json",
            payload,
        )

        new_latest = dict(latest)
        new_latest[agent.name] = payload
        new_history = list(state.get("position_history") or [])
        new_history.append(payload)
        return {
            "latest_positions": new_latest,
            "position_history": new_history,
        }

    return position_node


def _make_round_increment_node() -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a node that bumps the round counter after both agents have spoken."""

    def increment_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"round": state.get("round", 0) + 1}

    return increment_node


def _make_verifier_node() -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the Plan #34 verifier node.

    Runs after both agents have spoken in a round (between ``agent_b`` and
    ``round_increment``). Resolves every cited ``evidence_path`` in
    ``latest_positions``, tracks claim lineage against the prior round's
    positions, and appends entries to ``state["verifier_ledger"]``.

    Snapshots ``latest_positions`` into ``prior_positions_by_agent`` so the
    NEXT round's verifier can detect silent rename / silent retire.
    """

    def verifier_node(state: dict[str, Any]) -> dict[str, Any]:
        latest = state.get("latest_positions") or {}
        if not latest:
            return {}
        prior_by_agent = state.get("prior_positions_by_agent") or {}
        prior_ledger_entries = state.get("verifier_ledger") or []
        prior_ledger = VerifierLedger(
            entries=[LedgerEntry(**e) for e in prior_ledger_entries],
        )
        # Use the position's own round number — that's the round these
        # positions came FROM, regardless of where the router's state.round
        # has been incremented to.
        sample_round = next(iter(latest.values())).get("round", 0)
        workspace_path = state.get("task", {}).get("workspace_path", "")

        new_ledger = verify_round(
            latest_positions=latest,
            prior_positions_by_agent=prior_by_agent,
            prior_ledger=prior_ledger,
            round_num=int(sample_round),
            workspace_path=workspace_path,
        )

        # Persist after every round so a killed run still has the partial
        # ledger on disk.
        _persist_json(
            state["run_dir"],
            "verifier_ledger.json",
            new_ledger.to_dict(),
        )

        # Snapshot current → prior for next round's lineage checks.
        next_prior = {name: dict(pos) for name, pos in latest.items()}

        return {
            "verifier_ledger": [e.to_dict() for e in new_ledger.entries],
            "prior_positions_by_agent": next_prior,
        }

    return verifier_node


def _make_synthesis_node(
    synthesis_model: str,
    verdict: DeliberationVerdict,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the synthesis node: one LLM call to merge findings + residuals."""

    def synthesis_node(state: dict[str, Any]) -> dict[str, Any]:
        ctx = WorkflowContext.current(state, stage="deliberate.synthesis")
        task = state["task"]
        history = state.get("position_history") or []
        messages = _synthesis_prompt(task, history, verdict)
        # Synthesis schema is intentionally loose v1 — a Position with
        # ``disagreed_with_peer`` populated captures everything we need.
        # Future refinement: a SynthesisArtifact schema.
        synthesis_position, _meta = ctx.call_llm_structured(
            synthesis_model,
            messages,
            Position,
            timeout=DEFAULT_DELIBERATION_STAGE_TIMEOUT_S,
            codex_transport=DEFAULT_DELIBERATION_CODEX_TRANSPORT,
            cwd=task["workspace_path"],
        )
        payload = synthesis_position.model_dump()
        payload["agent_name"] = "synthesis"
        payload["round"] = state.get("round", 0)
        payload["reviewer_model"] = synthesis_model
        _persist_json(state["run_dir"], "synthesis.json", payload)
        return {"final_verdict": verdict}

    return synthesis_node


def _make_signoff_node(verdict: DeliberationVerdict) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the terminal signoff node."""

    def signoff_node(state: dict[str, Any]) -> dict[str, Any]:
        task = state["task"]
        run_dir = state["run_dir"]
        agents = state.get("agents") or []
        agent_names = [a["name"] for a in agents]
        history = state.get("position_history") or []
        residual: list[dict[str, Any]] = []
        for pos in (state.get("latest_positions") or {}).values():
            for dis in pos.get("disagreed_with_peer") or []:
                residual.append(dis)

        artifacts = {"task": "task.json", "synthesis": "synthesis.json"}
        if state.get("verifier_ledger"):
            artifacts["verifier_ledger"] = "verifier_ledger.json"
        for i, pos in enumerate(history):
            agent_name = pos.get("agent_name", f"unknown_{i}")
            round_num = pos.get("round", 0)
            artifacts[f"position_{agent_name}_round_{round_num}"] = (
                f"position_{agent_name}_round_{round_num}.json"
            )

        signoff = DeliberationSignoff(
            task_id=task.get("task_id", "?"),
            final_verdict=verdict,
            total_rounds=state.get("round", 0),
            agents=agent_names,
            residual_disagreements=[DisagreementAtom(**d) for d in residual],
            trace_id=state.get("_wf_trace_id", ""),
            artifacts_index=artifacts,
        )
        _persist_json(run_dir, "signoff.json", signoff.model_dump())
        return {"final_verdict": verdict}

    return signoff_node


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _make_post_round_router() -> Callable[[dict[str, Any]], str]:
    """After each round, decide whether to continue or terminate.

    Returns the next node name.
    """

    def router(state: dict[str, Any]) -> str:
        latest = state.get("latest_positions") or {}
        round_num = state.get("round", 0)
        max_rounds = state.get("max_rounds", 3)
        # Plan #34: thread the verifier ledger into the convergence check.
        ledger_entries = state.get("verifier_ledger") or []
        ledger: VerifierLedger | None = None
        if ledger_entries:
            ledger = VerifierLedger(
                entries=[LedgerEntry(**e) for e in ledger_entries],
            )
        verdict = detect_convergence(latest, round_num, max_rounds, ledger=ledger)
        if verdict is None:
            return "agent_a"  # continue to next round
        if verdict == "converged":
            return "synthesis_converged"
        if verdict == "stalled":
            return "signoff_stalled"
        # productive_disagreement
        return "synthesis_productive_disagreement"

    return router


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_deliberation_workflow(
    *,
    run_dir: str | Path,
    task: DeliberationTask | dict[str, Any],
    trace_id: str,
    max_budget: float,
    agents: list[tuple[str, str]] | None = None,
    max_rounds: int = 3,
    task_prefix: str = "deliberate",
    synthesis_model: str | None = None,
    checkpointer: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Build a compiled LangGraph app for the symmetric deliberation workflow.

    Args:
        run_dir: Directory for durable artifacts (created if missing).
        task: The deliberation task. Accepts ``DeliberationTask`` or a dict.
        trace_id: Shared trace_id across all LLM calls in the run.
        max_budget: USD budget for the entire run.
        agents: List of ``(name, model)`` pairs. Defaults to the
            ``DEFAULT_AGENT_PAIR`` (codex/gpt-5.4 + claude-code/opus).
            Two-agent only in v1; N-agent is a future extension.
        max_rounds: Cap on cycle count. Hitting this with residual
            disagreement promotes the verdict to ``productive_disagreement``.
        task_prefix: Task-label prefix for observability.
        synthesis_model: Model for the synthesis stage. Defaults to
            ``claude-code/opus`` for structured-output reliability.
        checkpointer: LangGraph checkpointer. Defaults to ``InMemorySaver``.

    Returns:
        ``(compiled_app, initial_state)``.

    Raises:
        ImportError: If ``langgraph`` is not installed.
        ValueError: If ``agents`` has fewer than 2 entries (v1 requires exactly 2).
    """
    from llm_client.workflow.builder import build_workflow

    task_obj = task if isinstance(task, DeliberationTask) else DeliberationTask(**task)
    task_dict = task_obj.model_dump()

    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)
    _persist_json(str(run_dir_path), "task.json", task_dict)

    pair = agents if agents is not None else list(DEFAULT_AGENT_PAIR)
    if len(pair) != 2:
        raise ValueError(
            f"Deliberation v1 requires exactly 2 agents; got {len(pair)}. "
            "N-agent (≥3) is a future extension; track in Plan #33 notes."
        )
    agent_a_name, agent_a_model = pair[0]
    agent_b_name, agent_b_model = pair[1]
    agent_a = DeliberationAgent(name=agent_a_name, model=agent_a_model)
    agent_b = DeliberationAgent(name=agent_b_name, model=agent_b_model)

    resolved_synthesis = synthesis_model or "claude-code/opus"

    agent_a_node = _make_agent_position_node(agent_a, peer_name=agent_b_name)
    agent_b_node = _make_agent_position_node(agent_b, peer_name=agent_a_name)
    verifier_node = _make_verifier_node()
    increment_node = _make_round_increment_node()
    synthesis_converged_node = _make_synthesis_node(resolved_synthesis, "converged")
    synthesis_pd_node = _make_synthesis_node(resolved_synthesis, "productive_disagreement")
    signoff_pass_node = _make_signoff_node("converged")
    signoff_pd_node = _make_signoff_node("productive_disagreement")
    signoff_stalled_node = _make_signoff_node("stalled")

    post_round_router = _make_post_round_router()

    config = WorkflowConfig.from_dict({
        "task_prefix": task_prefix,
        "max_budget": max_budget,
    })

    # Round topology: agent_a → agent_b → verifier → round_increment → router
    #   verifier resolves cited evidence + tracks claim lineage (Plan #34).
    #   router → agent_a (continue) | synthesis_converged | synthesis_productive_disagreement | signoff_stalled
    #   synthesis_converged → signoff_pass
    #   synthesis_productive_disagreement → signoff_pd
    app = build_workflow(
        state_schema=DeliberationState,
        config=config,
        nodes={
            "agent_a": agent_a_node,
            "agent_b": agent_b_node,
            "verifier": verifier_node,
            "round_increment": increment_node,
            "synthesis_converged": synthesis_converged_node,
            "synthesis_productive_disagreement": synthesis_pd_node,
            "signoff_pass": signoff_pass_node,
            "signoff_pd": signoff_pd_node,
            "signoff_stalled": signoff_stalled_node,
        },
        edges=[
            ("agent_a", "agent_b"),
            ("agent_b", "verifier"),
            ("verifier", "round_increment"),
            ("synthesis_converged", "signoff_pass"),
            ("synthesis_productive_disagreement", "signoff_pd"),
        ],
        conditional_edges={
            "round_increment": post_round_router,
        },
        entry_point="agent_a",
        finish_points=["signoff_pass", "signoff_pd", "signoff_stalled"],
        checkpointer=checkpointer,
    )

    ctx = WorkflowContext(
        trace_id=trace_id,
        max_budget=max_budget,
        task_prefix=task_prefix,
    )
    initial_state: dict[str, Any] = ctx.inject_into_state({
        "task": task_dict,
        "run_dir": str(run_dir_path),
        "round": 1,
        "max_rounds": max_rounds,
        "agents": [{"name": agent_a_name, "model": agent_a_model},
                   {"name": agent_b_name, "model": agent_b_model}],
        "latest_positions": {},
        "prior_positions_by_agent": {},
        "position_history": [],
        "verifier_ledger": [],
    })

    return app, initial_state


__all__ = [
    "LedgerEntry",
    "VerifierLedger",
    "DeliberationVerdict",
    "PositionState",
    "Confidence",
    "ClaimSeverity",
    "DEFAULT_AGENT_PAIR",
    "DeliberationTask",
    "PositionClaim",
    "PositionEvidence",
    "DisagreementAtom",
    "Position",
    "DeliberationSignoff",
    "DeliberationAgent",
    "DeliberationState",
    "detect_convergence",
    "build_deliberation_workflow",
]
