"""Measure whether a claim judge blocks on real problems or on wording.

The natural way to test a judge is to run it twice and see whether it agrees
with itself. That measures the wrong thing. An LLM judge will not be
deterministic, and it does not need to be: two defensible verdicts that differ
are fine, and a run-to-run diff cannot tell those apart from one verdict that is
simply wrong.

What matters is whether each block is *defensible* — whether a careful reader
would agree the thing it blocked on is actually wrong. That is the failure this
whole area exists to prevent: a judge that blocks a run because "substantial" is
not stated in those exact words, while arguing the point carefully enough to
look substantive.

So this module re-reads each blocking judgment and rules on the objection rather
than on the claim, sorting objections into ones that identify a real error and
ones that are really about phrasing. The headline number is the share of blocks
that hold up. A judge blocking ten times with nine stylistic objections is
worse than one blocking twice with two substantive ones, and no agreement
metric will tell you that.

Usage::

    from llm_client.claim_adjudication import adjudicate_blocks

    result = adjudicate_blocks(
        blocks,
        context={"bayesian": bayesian_json},
        task="pt.block_review",
        trace_id="run/adjudication",
        max_budget=2.0,
        model="openrouter/openai/gpt-5.6-luna",
        reasoning_effort="medium",
    )
    result.defensible_rate      # share of blocks that hold up
    result.stylistic_blocks     # the regression this exists to catch
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

ADJUDICATION_PROMPT_REF = "shared.claim_verification.block_adjudication@1"

Ruling = Literal["upheld", "stylistic", "overreaching", "unclear"]

#: Rulings under which the block was not warranted. `unclear` is deliberately
#: absent: an undecidable objection is a reporting problem, not a pass or a
#: fail, and folding it into either direction hides it.
UNWARRANTED_RULINGS: frozenset[str] = frozenset({"stylistic", "overreaching"})


class BlockUnderReview(BaseModel):
    """One blocking judgment to be ruled on."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str = Field(min_length=1)
    severity: str = Field(description="The tier the judge assigned.")
    objection: str = Field(
        min_length=1, description="The judge's stated reason for blocking."
    )
    supports: list[dict[str, Any]] = Field(
        default_factory=list, description="Provenance the claim cited."
    )


class BlockVerdict(BaseModel):
    """A ruling on whether one block was warranted."""

    model_config = ConfigDict(extra="forbid")

    ruling: Ruling = Field(
        description=(
            "upheld = the objection is correct; "
            "stylistic = it is really about wording; "
            "overreaching = it is about substance but wrong; "
            "unclear = the material does not allow a call."
        )
    )
    reasoning: str = Field(
        min_length=12,
        description="One or more sentences naming what decided the ruling.",
    )

    @property
    def block_warranted(self) -> bool:
        """Whether this ruling supports the judge having blocked."""
        return self.ruling == "upheld"


class AdjudicatedBlock(BaseModel):
    """One block paired with its ruling."""

    model_config = ConfigDict(extra="forbid")

    block: BlockUnderReview
    verdict: BlockVerdict
    model: str = Field(default="", description="Model that issued this ruling.")


class AdjudicationResult(BaseModel):
    """How well a judge's blocking behaviour holds up."""

    model_config = ConfigDict(extra="forbid")

    adjudicated: list[AdjudicatedBlock]

    @property
    def total(self) -> int:
        return len(self.adjudicated)

    @property
    def upheld(self) -> list[AdjudicatedBlock]:
        """Blocks whose objection was correct."""
        return [a for a in self.adjudicated if a.verdict.ruling == "upheld"]

    @property
    def stylistic_blocks(self) -> list[AdjudicatedBlock]:
        """Blocks that were really about wording — the regression to watch."""
        return [a for a in self.adjudicated if a.verdict.ruling == "stylistic"]

    @property
    def unwarranted(self) -> list[AdjudicatedBlock]:
        """Blocks that should not have blocked, for any reason."""
        return [a for a in self.adjudicated if a.verdict.ruling in UNWARRANTED_RULINGS]

    @property
    def unclear(self) -> list[AdjudicatedBlock]:
        """Blocks the adjudicator could not rule on."""
        return [a for a in self.adjudicated if a.verdict.ruling == "unclear"]

    @property
    def disputed(self) -> list[str]:
        """Claim IDs where adjudicators disagreed about whether the block held.

        Empirically the most useful output of the whole check. Two models split
        on one real block because the *prose* was ambiguous — "the leading rank
        can change" reads either as the ranking order or as the identity of the
        leader, and both readings are defensible. A disagreement here localizes
        ambiguity in the writing under review, which neither verdict alone does.
        """
        by_claim: dict[str, set[bool]] = {}
        for a in self.adjudicated:
            if a.verdict.ruling == "unclear":
                continue
            by_claim.setdefault(a.block.claim_id, set()).add(a.verdict.block_warranted)
        return sorted(cid for cid, calls in by_claim.items() if len(calls) > 1)

    @property
    def defensible_rate(self) -> float | None:
        """Share of decidable blocks that were warranted.

        `None` when nothing was decidable, which is not the same as 0.0 and must
        not be reported as a failing score.
        """
        decidable = self.total - len(self.unclear)
        if decidable <= 0:
            return None
        return len(self.upheld) / decidable

    def summary(self) -> str:
        """One line suitable for a run log or a check's output."""
        if not self.total:
            return "no blocking claims to adjudicate"
        rate = self.defensible_rate
        rate_text = "n/a" if rate is None else f"{rate:.0%}"
        return (
            f"{self.total} block(s): {len(self.upheld)} upheld, "
            f"{len(self.stylistic_blocks)} stylistic, "
            f"{len(self.unwarranted) - len(self.stylistic_blocks)} overreaching, "
            f"{len(self.unclear)} unclear — defensible {rate_text}"
        )


def blocks_from_claims(
    claims: list[Any],
    *,
    blocking_severities: set[str],
) -> list[BlockUnderReview]:
    """Extract the blocking judgments from a judge's claims.

    Accepts any claim object exposing ``claim_id``, ``claim_text``, ``severity``
    and ``reasoning``, so this works against both the shared
    :class:`~llm_client.claim_verification.VerifiedClaim` and a project's own
    claim model without importing it.
    """
    blocks: list[BlockUnderReview] = []
    for claim in claims:
        severity = getattr(claim, "severity", None)
        if severity not in blocking_severities:
            continue
        supports = getattr(claim, "supports", []) or []
        blocks.append(
            BlockUnderReview(
                claim_id=getattr(claim, "claim_id", "?"),
                claim_text=getattr(claim, "claim_text", "") or "(no text)",
                severity=str(severity),
                objection=getattr(claim, "reasoning", "") or "(no reasoning given)",
                supports=[
                    s.model_dump(mode="json") if hasattr(s, "model_dump") else dict(s)
                    for s in supports
                ],
            )
        )
    return blocks


def adjudicate_blocks(
    blocks: list[BlockUnderReview],
    *,
    context: Any,
    task: str,
    trace_id: str,
    max_budget: float,
    model: str | list[str],
    **call_kwargs: Any,
) -> AdjudicationResult:
    """Rule on each block independently.

    One call per block, deliberately. Batching invites the adjudicator to
    compare blocks against each other and grade on a curve, when the question is
    whether each objection stands on its own.

    Args:
        blocks: Blocking judgments to rule on.
        context: Evidence and artifact values the claims were judged against.
        task: Required observability task tag.
        trace_id: Required observability trace ID; each block appends its id.
        max_budget: Required spend ceiling, applied per block.
        model: Adjudicating model, or several. Prefer several, and prefer at
            least one from a different family than the judge under review: a
            single adjudicator was measured disagreeing with another on a real
            block, and a model is a poor reviewer of its own habits. Where they
            split, see :attr:`AdjudicationResult.disputed`.
        **call_kwargs: Passed to ``call_llm_structured``.

    Returns:
        :class:`AdjudicationResult`.
    """
    from llm_client.core.client import call_llm_structured
    from llm_client.prompts import render_prompt

    models = [model] if isinstance(model, str) else list(model)
    if not models:
        raise ValueError("at least one adjudicating model is required")
    context_json = json.dumps(context, indent=2, default=str)
    adjudicated: list[AdjudicatedBlock] = []
    for block in blocks:
        messages = render_prompt(
            prompt_ref=ADJUDICATION_PROMPT_REF,
            claim_json=json.dumps(
                {"claim_id": block.claim_id, "claim_text": block.claim_text},
                indent=2,
            ),
            objection=block.objection,
            supports_json=json.dumps(block.supports, indent=2, default=str),
            context_json=context_json,
        )
        for adjudicator in models:
            verdict, _result = call_llm_structured(
                adjudicator,
                messages,
                response_model=BlockVerdict,
                task=task,
                trace_id=f"{trace_id}/{block.claim_id}/{adjudicator.rsplit('/', 1)[-1]}",
                max_budget=max_budget,
                **call_kwargs,
            )
            adjudicated.append(
                AdjudicatedBlock(block=block, verdict=verdict, model=adjudicator)
            )

    result = AdjudicationResult(adjudicated=adjudicated)
    if result.disputed:
        logger.warning(
            "adjudicators disagreed on %d block(s), which usually means the "
            "reviewed prose is ambiguous: %s",
            len(result.disputed),
            ", ".join(result.disputed),
        )
    if result.stylistic_blocks:
        logger.warning(
            "%d of %d block(s) were wording objections: %s",
            len(result.stylistic_blocks),
            result.total,
            ", ".join(a.block.claim_id for a in result.stylistic_blocks),
        )
    return result
