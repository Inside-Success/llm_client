"""Tests for the deliberation workflow.

Stubs the LLM calls at the ``WorkflowContext`` integration seam so the
LangGraph wiring, convergence detector, position threading, and artifact
persistence can be exercised offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

try:
    import langgraph  # noqa: F401

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False

pytestmark = pytest.mark.skipif(not HAS_LANGGRAPH, reason="langgraph not installed")

from llm_client.workflow.deliberate import (  # noqa: E402
    DeliberationTask,
    DisagreementAtom,
    Position,
    PositionClaim,
    build_deliberation_workflow,
    detect_convergence,
)


@dataclass
class _StubResult:
    content: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    model: str = "stub"


class _DeliberationHarness:
    """Captures stub call sequence + drives one Position per LLM call."""

    def __init__(self) -> None:
        self.call_log: list[tuple[str, str]] = []  # (agent_or_synthesis, model)
        self.call_messages: list[list[dict[str, Any]]] = []
        # Per-agent queue of Position objects. Key by agent name; synthesis
        # uses key "synthesis".
        self.positions: dict[str, list[Position]] = {}

    def push(self, agent: str, position: Position) -> None:
        self.positions.setdefault(agent, []).append(position)

    def call_llm_structured(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response_model: type,
        **kwargs: Any,
    ) -> tuple[Any, _StubResult]:
        # Determine which agent this call is for by inspecting the system /
        # user message for the agent name marker.
        user_blob = messages[-1]["content"]
        if "## Your role: agent_a" in user_blob:
            key = "agent_a"
        elif "## Your role: agent_b" in user_blob:
            key = "agent_b"
        else:
            key = "synthesis"
        self.call_log.append((key, model))
        self.call_messages.append(messages)
        queue = self.positions.get(key, [])
        if not queue:
            raise AssertionError(f"No stub position queued for {key!r} model={model!r}")
        return queue.pop(0), _StubResult(model=model)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _DeliberationHarness:
    h = _DeliberationHarness()

    def fake_call_llm_structured(model, messages, response_model, **kwargs):
        return h.call_llm_structured(model, messages, response_model, **kwargs)

    monkeypatch.setattr("llm_client.core.client.call_llm_structured", fake_call_llm_structured)
    return h


def _task(workspace: Path) -> DeliberationTask:
    return DeliberationTask(
        task_id="t1",
        title="Should we adopt approach X?",
        question="Approach X has tradeoff Y. Should we adopt?",
        workspace_path=str(workspace),
        success_criteria=["both agents agree on tradeoffs", "no overclaim"],
        constraints=["evidence_path required on every claim"],
    )


def _claim(claim_id: str, claim: str, evidence: str = "foo.py:1") -> PositionClaim:
    return PositionClaim(claim_id=claim_id, claim=claim, evidence_path=evidence)


def _run(app: Any, init: dict[str, Any], thread_id: str) -> dict[str, Any]:
    return app.invoke(init, config={"configurable": {"thread_id": thread_id}})


# ---------------------------------------------------------------------------
# Convergence detector (pure-Python; no LangGraph needed)
# ---------------------------------------------------------------------------


def test_detect_convergence_returns_none_before_round_2() -> None:
    """Round 1 hasn't seen cross-agent exchange yet — never terminal-converged."""
    positions = {
        "agent_a": Position(agent_name="agent_a", round=1, claims=[_claim("c1", "X")]).model_dump(),
        "agent_b": Position(agent_name="agent_b", round=1, claims=[_claim("c2", "Y")]).model_dump(),
    }
    assert detect_convergence(positions, round_num=1, max_rounds=3) is None


def test_detect_convergence_returns_converged_on_mutual_agreement() -> None:
    """Round >= 2, no disagreements, each agreed_with_peer covers peer's claim IDs."""
    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=["b1"], disagreed_with_peer=[],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    assert detect_convergence(positions, round_num=2, max_rounds=3) == "converged"


def test_detect_convergence_returns_none_when_peer_claim_not_acknowledged() -> None:
    """Even with no disagreement entries, if an agent missed a peer claim, not converged."""
    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=[], disagreed_with_peer=[],  # missed b1
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    assert detect_convergence(positions, round_num=2, max_rounds=3) is None


def test_detect_convergence_returns_productive_disagreement_at_round_cap() -> None:
    """Round == max_rounds with residual disagreement → productive_disagreement."""
    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=3, claims=[_claim("a1", "X")],
            disagreed_with_peer=[DisagreementAtom(peer_claim_id="b1", my_counterclaim="not Y", evidence_path="bar.py:2")],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=3, claims=[_claim("b1", "Y")],
        ).model_dump(),
    }
    assert detect_convergence(positions, round_num=3, max_rounds=3) == "productive_disagreement"


def test_detect_convergence_returns_stalled_when_both_positions_empty() -> None:
    """If both agents emit zero claims, deliberation has stalled."""
    positions = {
        "agent_a": Position(agent_name="agent_a", round=1).model_dump(),
        "agent_b": Position(agent_name="agent_b", round=1).model_dump(),
    }
    assert detect_convergence(positions, round_num=1, max_rounds=3) == "stalled"


# ---------------------------------------------------------------------------
# Schema groundedness (validation tests; no harness needed)
# ---------------------------------------------------------------------------


def test_position_claim_requires_evidence_path() -> None:
    """A claim without evidence_path is unfalsifiable; schema rejects it."""
    import pydantic

    PositionClaim(claim_id="c1", claim="X", evidence_path="foo.py:1")  # ok
    with pytest.raises(pydantic.ValidationError, match="evidence_path"):
        PositionClaim(claim_id="c1", claim="X")  # type: ignore[call-arg]


def test_disagreement_atom_requires_evidence_path() -> None:
    """Disagreement is grounded too — can't disagree without a citation."""
    import pydantic

    DisagreementAtom(peer_claim_id="b1", my_counterclaim="not Y", evidence_path="x.py:1")
    with pytest.raises(pydantic.ValidationError, match="evidence_path"):
        DisagreementAtom(peer_claim_id="b1", my_counterclaim="not Y")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# End-to-end (stubbed) workflow tests
# ---------------------------------------------------------------------------


def test_round_1_produces_independent_positions(harness: _DeliberationHarness, tmp_path: Path) -> None:
    """Round 1: agent_a writes first, agent_b second. Neither has peer context
    on its own first call (agent_a's first prompt has no peer; agent_b's first
    prompt may have agent_a's round-1 position).
    """
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Plan #34 verifier resolves cited evidence_path; ``_claim`` defaults to
    # ``foo.py:1`` so make sure that file exists in the workspace, otherwise
    # the verifier marks every claim as ``file_not_found`` and blocks
    # converged.
    (workspace / "foo.py").write_text("line 1\n")

    # Agent A converges immediately (round 1 + nothing to disagree on).
    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "X is true")],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "Y is true")],
        agreed_with_peer=["a1"], disagreed_with_peer=[],
    ))
    # Round 2: both agree, convergence detector fires.
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "X is true")],
        agreed_with_peer=["b1"], disagreed_with_peer=[], state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "Y is true")],
        agreed_with_peer=["a1"], disagreed_with_peer=[], state="stable",
    ))
    # Synthesis call.
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[], reviewer_summary="Both agreed.",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-round1",
        max_budget=1.0,
        max_rounds=3,
    )
    result = _run(app, init, "t-round1")

    # First call (agent_a round 1) had no peer position.
    first_msg = harness.call_messages[0][-1]["content"]
    assert "None yet — this is round 1." in first_msg

    # By the time agent_a runs round 2, it sees agent_b's round-1 position.
    # Find the agent_a-round-2 message in the log.
    agent_a_calls = [i for i, (k, _) in enumerate(harness.call_log) if k == "agent_a"]
    assert len(agent_a_calls) >= 2
    agent_a_round_2 = harness.call_messages[agent_a_calls[1]][-1]["content"]
    assert "Peer's most-recent position" in agent_a_round_2
    assert "b1" in agent_a_round_2  # agent_b's claim id leaked into the prompt

    assert result["final_verdict"] == "converged"


def test_cycle_cap_promotes_to_productive_disagreement(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Both agents disagree across max_rounds → productive_disagreement."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    # max_rounds=2; both agents disagree across rounds.
    for round_num in (1, 2):
        harness.push("agent_a", Position(
            agent_name="agent_a", round=round_num, claims=[_claim("a1", "X")],
            disagreed_with_peer=[DisagreementAtom(peer_claim_id="b1", my_counterclaim="not Y", evidence_path="bar:1")],
        ))
        harness.push("agent_b", Position(
            agent_name="agent_b", round=round_num, claims=[_claim("b1", "Y")],
            disagreed_with_peer=[DisagreementAtom(peer_claim_id="a1", my_counterclaim="not X", evidence_path="bar:2")],
        ))
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[],
        disagreed_with_peer=[DisagreementAtom(peer_claim_id="a1", my_counterclaim="unresolved", evidence_path="bar:3")],
        reviewer_summary="They disagreed throughout.",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-pd",
        max_budget=1.0,
        max_rounds=2,
    )
    result = _run(app, init, "t-pd")

    assert result["final_verdict"] == "productive_disagreement"
    # Synthesis runs even on productive_disagreement — surfaces residuals.
    assert (run_dir / "synthesis.json").exists()


def test_stalled_when_both_agents_emit_empty_positions(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Both agents return zero claims → terminal `stalled`."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    harness.push("agent_a", Position(agent_name="agent_a", round=1, claims=[]))
    harness.push("agent_b", Position(agent_name="agent_b", round=1, claims=[]))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-stall",
        max_budget=1.0,
        max_rounds=3,
    )
    result = _run(app, init, "t-stall")

    assert result["final_verdict"] == "stalled"
    # Stalled is terminal — no synthesis call expected.
    assert "synthesis" not in dict(harness.call_log)


def test_two_agent_default_uses_codex_and_claude_code(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """When agents=None, defaults to codex/gpt-5.4 + claude-code/sonnet."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "X")],
        agreed_with_peer=[], disagreed_with_peer=[],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "Y")],
        agreed_with_peer=["a1"], disagreed_with_peer=[],
    ))
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
        agreed_with_peer=["b1"], disagreed_with_peer=[], state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
        agreed_with_peer=["a1"], disagreed_with_peer=[], state="stable",
    ))
    harness.push("synthesis", Position(agent_name="synthesis", round=2, claims=[]))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-default-agents",
        max_budget=1.0,
        # agents=None to exercise the default.
    )
    _run(app, init, "t-default-agents")

    models_seen = {model for _, model in harness.call_log}
    assert "codex/gpt-5.4" in models_seen
    assert "claude-code/sonnet" in models_seen


def test_position_artifacts_persisted_to_run_dir(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Each round's position lands as a JSON artifact in run_dir."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "X")],
        agreed_with_peer=[], disagreed_with_peer=[],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "Y")],
        agreed_with_peer=["a1"], disagreed_with_peer=[],
    ))
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
        agreed_with_peer=["b1"], disagreed_with_peer=[], state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
        agreed_with_peer=["a1"], disagreed_with_peer=[], state="stable",
    ))
    harness.push("synthesis", Position(agent_name="synthesis", round=2, claims=[]))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-art",
        max_budget=1.0,
    )
    _run(app, init, "t-art")

    expected = {
        "task.json",
        "position_agent_a_round_1.json",
        "position_agent_b_round_1.json",
        "position_agent_a_round_2.json",
        "position_agent_b_round_2.json",
        "synthesis.json",
        "signoff.json",
        "verifier_ledger.json",  # Plan #34
    }
    actual = {p.name for p in run_dir.iterdir() if p.is_file()}
    assert expected.issubset(actual), f"missing: {expected - actual}"


# ---------------------------------------------------------------------------
# Plan #34: verifier-gated convergence
# ---------------------------------------------------------------------------


def test_detect_convergence_backward_compat_without_ledger() -> None:
    """detect_convergence(latest, round, max, ledger=None) preserves Plan-#33 behavior."""
    from llm_client.workflow.deliberate import detect_convergence

    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=["b1"], disagreed_with_peer=[],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    # No ledger arg → backward compat → converged.
    assert detect_convergence(positions, round_num=2, max_rounds=3) == "converged"


def test_detect_convergence_refused_when_ledger_has_unverified_in_latest_round() -> None:
    """Even with agreement metadata complete, an unverified ledger entry in the
    latest round blocks the converged verdict.
    """
    from llm_client.workflow.deliberate import detect_convergence
    from llm_client.workflow.deliberate_verifier import LedgerEntry, VerifierLedger

    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=["b1"], disagreed_with_peer=[],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    ledger = VerifierLedger()
    ledger.extend([
        LedgerEntry(
            agent_name="agent_a", round=2, claim_id="a1",
            evidence_path="bogus.py:1", status="file_not_found",
        ),
    ])
    # Ledger has an unverified citation in round 2 → refuses converged.
    assert detect_convergence(positions, round_num=2, max_rounds=3, ledger=ledger) is None


def test_detect_convergence_refused_when_lineage_flag_in_latest_round() -> None:
    """A silent_rename flag in the latest round blocks converged."""
    from llm_client.workflow.deliberate import detect_convergence
    from llm_client.workflow.deliberate_verifier import LedgerEntry, VerifierLedger

    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=["b1"], disagreed_with_peer=[],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    ledger = VerifierLedger()
    ledger.extend([
        LedgerEntry(
            agent_name="agent_a", round=2, claim_id="a1",
            evidence_path="foo.py:1", status="verified",
        ),
        LedgerEntry(
            agent_name="agent_a", round=2, claim_id="a1_renamed",
            evidence_path="", status="content_mismatch_warning",
            lineage_flag="silent_rename",
        ),
    ])
    assert detect_convergence(positions, round_num=2, max_rounds=3, ledger=ledger) is None


def test_detect_convergence_fires_when_ledger_is_clean() -> None:
    """When agents agree AND the ledger has only verified entries in the
    latest round, converged still fires.
    """
    from llm_client.workflow.deliberate import detect_convergence
    from llm_client.workflow.deliberate_verifier import LedgerEntry, VerifierLedger

    positions = {
        "agent_a": Position(
            agent_name="agent_a", round=2, claims=[_claim("a1", "X")],
            agreed_with_peer=["b1"], disagreed_with_peer=[],
        ).model_dump(),
        "agent_b": Position(
            agent_name="agent_b", round=2, claims=[_claim("b1", "Y")],
            agreed_with_peer=["a1"], disagreed_with_peer=[],
        ).model_dump(),
    }
    ledger = VerifierLedger()
    ledger.extend([
        LedgerEntry(
            agent_name="agent_a", round=2, claim_id="a1",
            evidence_path="x.py:1", status="verified",
        ),
        LedgerEntry(
            agent_name="agent_b", round=2, claim_id="b1",
            evidence_path="y.py:2", status="verified",
        ),
    ])
    assert detect_convergence(positions, round_num=2, max_rounds=3, ledger=ledger) == "converged"


def test_wrong_agent_count_raises_at_build_time(tmp_path: Path) -> None:
    """v1 only supports exactly 2 agents; ≠2 must fail loud."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with pytest.raises(ValueError, match="exactly 2 agents"):
        build_deliberation_workflow(
            run_dir=run_dir,
            task=_task(workspace),
            trace_id="t-bad",
            max_budget=1.0,
            agents=[("only_one", "codex/gpt-5.4")],
        )

    with pytest.raises(ValueError, match="exactly 2 agents"):
        build_deliberation_workflow(
            run_dir=run_dir,
            task=_task(workspace),
            trace_id="t-bad-3",
            max_budget=1.0,
            agents=[
                ("a", "codex/gpt-5.4"),
                ("b", "claude-code/sonnet"),
                ("c", "codex/gpt-5.4"),
            ],
        )


# ---------------------------------------------------------------------------
# Plan #35: Within-Round Barrier Protocol
#
# Contract: in round N, agent_b reads agent_a's round-(N-1) position from
# prior_positions_by_agent, NOT agent_a's freshest round-N position from
# latest_positions. This eliminates the same-round second-mover advantage
# the cascade topology would otherwise grant. The verifier publishes
# prior_positions_by_agent at end-of-round, so within a round both agents
# read the same round-(N-1) snapshot.
#
# References: Du et al. arXiv:2305.14325; 2603.28813; 2510.07517. See
# docs/plans/35_deliberation_within_round_barrier_protocol.md.
# ---------------------------------------------------------------------------


def test_barrier_round_1_both_agents_see_empty_peer_state(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Round 1: prior_positions_by_agent is empty, so both agents see
    'None yet — this is round 1.' regardless of execution order."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo.py").write_text("line 1\n")

    # Round 1
    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "AGENT_A_R1_MARKER")],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "AGENT_B_R1_MARKER")],
    ))
    # Round 2 to satisfy max_rounds and let synthesis fire
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "AGENT_A_R2_MARKER")],
        state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "AGENT_B_R2_MARKER")],
        state="stable",
    ))
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[],
        reviewer_summary="done",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-barrier-r1",
        max_budget=1.0,
        max_rounds=2,
    )
    _run(app, init, "t-barrier-r1")

    # Both round-1 prompts should report no peer state. Under the cascade
    # topology this assertion would fail for agent_b — the bug Plan #35 fixes.
    agent_a_r1_prompt = harness.call_messages[0][-1]["content"]
    agent_b_r1_prompt = harness.call_messages[1][-1]["content"]
    assert "None yet — this is round 1." in agent_a_r1_prompt
    assert "None yet — this is round 1." in agent_b_r1_prompt
    assert "AGENT_A_R1_MARKER" not in agent_b_r1_prompt, (
        "BARRIER VIOLATION: agent_b's round-1 prompt should not contain "
        "agent_a's round-1 marker — that's same-round second-mover leakage."
    )


def test_barrier_round_2_agent_b_sees_round_1_not_round_2(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Round 2: agent_b's prompt must contain agent_a's round-1 marker,
    not agent_a's freshest round-2 marker, even though agent_a writes
    round-2 first within the round's edge sequence."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo.py").write_text("line 1\n")

    # Round 1
    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "AGENT_A_R1_MARKER")],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "AGENT_B_R1_MARKER")],
    ))
    # Round 2 — agent_a emits a different marker
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "AGENT_A_R2_MARKER")],
        state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "AGENT_B_R2_MARKER")],
        state="stable",
    ))
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[], reviewer_summary="done",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-barrier-r2",
        max_budget=1.0,
        max_rounds=3,
    )
    _run(app, init, "t-barrier-r2")

    # Find agent_b round-2 prompt
    agent_b_calls = [i for i, (k, _) in enumerate(harness.call_log) if k == "agent_b"]
    assert len(agent_b_calls) >= 2
    agent_b_r2_prompt = harness.call_messages[agent_b_calls[1]][-1]["content"]

    # MUST contain agent_a's round-1 content (the barrier snapshot)
    assert "AGENT_A_R1_MARKER" in agent_b_r2_prompt, (
        "agent_b round-2 prompt is missing agent_a's round-1 marker — "
        "the barrier should expose round-(N-1) peer state."
    )
    # MUST NOT contain agent_a's freshest round-2 content
    assert "AGENT_A_R2_MARKER" not in agent_b_r2_prompt, (
        "BARRIER VIOLATION: agent_b round-2 prompt contains agent_a's freshest "
        "round-2 marker — this is the same-round second-mover leak that "
        "Plan #35's barrier protocol prevents."
    )


def test_anonymization_strips_peer_agent_name_and_reviewer_model(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Plan #35 Phase 2: peer_latest serialized into the prompt must not
    contain the peer's agent_name or reviewer_model — those leak identity
    and trigger the conformity/obstinacy bias documented in arXiv:2510.07517."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo.py").write_text("line 1\n")

    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "AGENT_A_R1")],
        reviewer_model="claude-code/sonnet",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "AGENT_B_R1")],
        reviewer_model="codex/gpt-5.4",
    ))
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "AGENT_A_R2")],
        state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "AGENT_B_R2")],
        state="stable",
    ))
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[], reviewer_summary="done",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-anon",
        max_budget=1.0,
        max_rounds=3,
    )
    _run(app, init, "t-anon")

    # Check agent_a's round-2 prompt — peer state (agent_b's round-1) must
    # be anonymized. The peer's reviewer_model ("codex/gpt-5.4") and the
    # peer's agent_name ("agent_b") must not appear in the rendered JSON.
    agent_a_calls = [i for i, (k, _) in enumerate(harness.call_log) if k == "agent_a"]
    agent_a_r2 = harness.call_messages[agent_a_calls[1]][-1]["content"]

    # Extract just the "Peer's most-recent position" section, bounded by
    # the next "##" header (typically "## Your prior position" which
    # legitimately contains the agent's own model identity).
    peer_section_start = agent_a_r2.find("## Peer's most-recent position")
    assert peer_section_start >= 0
    next_header = agent_a_r2.find("\n## ", peer_section_start + 1)
    peer_section = (
        agent_a_r2[peer_section_start:next_header]
        if next_header > 0
        else agent_a_r2[peer_section_start:]
    )

    assert '"agent_name": "agent_b"' not in peer_section, (
        "peer agent_name leaked into prompt — anonymization failed"
    )
    assert "codex/gpt-5.4" not in peer_section, (
        "peer reviewer_model leaked into prompt — anonymization failed"
    )
    # The neutral label SHOULD appear
    assert '"agent_name": "peer"' in peer_section

    # The agent's OWN role header should still use its own real name
    # (anonymization only hides peer identity, not self identity)
    assert "## Your role: agent_a" in agent_a_r2

    # Claim IDs MUST still pass through (the verifier needs them)
    assert "b1" in peer_section


def test_barrier_round_2_agent_a_sees_round_1_peer_state(
    harness: _DeliberationHarness, tmp_path: Path
) -> None:
    """Round 2: agent_a runs first and reads agent_b's round-1 from the
    snapshot. Confirms the snapshot publishes correctly at end-of-round-1."""
    run_dir = tmp_path / "run"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "foo.py").write_text("line 1\n")

    harness.push("agent_a", Position(
        agent_name="agent_a", round=1, claims=[_claim("a1", "AGENT_A_R1_MARKER")],
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=1, claims=[_claim("b1", "AGENT_B_R1_MARKER")],
    ))
    harness.push("agent_a", Position(
        agent_name="agent_a", round=2, claims=[_claim("a1", "AGENT_A_R2_MARKER")],
        state="stable",
    ))
    harness.push("agent_b", Position(
        agent_name="agent_b", round=2, claims=[_claim("b1", "AGENT_B_R2_MARKER")],
        state="stable",
    ))
    harness.push("synthesis", Position(
        agent_name="synthesis", round=2, claims=[], reviewer_summary="done",
    ))

    app, init = build_deliberation_workflow(
        run_dir=run_dir,
        task=_task(workspace),
        trace_id="t-barrier-r2a",
        max_budget=1.0,
        max_rounds=3,
    )
    _run(app, init, "t-barrier-r2a")

    agent_a_calls = [i for i, (k, _) in enumerate(harness.call_log) if k == "agent_a"]
    assert len(agent_a_calls) >= 2
    agent_a_r2_prompt = harness.call_messages[agent_a_calls[1]][-1]["content"]

    assert "AGENT_B_R1_MARKER" in agent_a_r2_prompt, (
        "agent_a round-2 prompt should contain agent_b's round-1 marker "
        "from the snapshot."
    )
