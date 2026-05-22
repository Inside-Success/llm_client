"""Deliberation verifier / adjudicator stage (Plan #34).

Pure-Python verifier that resolves cited evidence into a per-claim ledger and
drives the convergence detector from the ledger instead of from agents'
self-reported ``agreed_with_peer`` / ``disagreed_with_peer`` metadata.

Why this exists: Plan #33's deliberation chassis trusted agents to report
their own agreement honestly. Plan #33's own self-deliberation surfaced two
structural weaknesses that motivated this stage:

- Agents can rename a claim between rounds (same content, different
  ``claim_id``) and the convergence rule silently treats them as different
  claims.
- ``evidence_path`` is a bare ``str`` — schema accepts ``"because I said so"``.
  Nothing opens the cited file or checks the citation resolves.

This module:

1. Parses ``evidence_path`` strings into ``(file_path, line_range)`` references.
2. Resolves each reference against the workspace and attaches a content
   snippet from the cited range.
3. Tracks claim lineage across rounds: detects silent rename, silent retire,
   and fabricated peer references.
4. Builds a ledger consumed by ``detect_convergence`` so the convergence
   verdict depends on verified evidence, not self-reports.

Design: pure-Python, no LLM, no network. Deterministic. The chassis is
augmented, not replaced — agents' Position fields stay on disk for human
consumers; the ledger is the source of truth for the router.

See ``docs/plans/34_deliberation_verifier_adjudicator.md`` for the full design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

LedgerStatus = Literal[
    "verified",
    "unresolved_path",
    "unparseable_evidence",
    "file_not_found",
    "content_mismatch_warning",
]

LineageFlag = Literal[
    "silent_rename",
    "silent_retire",
    "fabricated_peer_ref",
]


@dataclass
class LedgerEntry:
    """One row of the per-claim verification ledger.

    Created either by ``verify_position`` (one per ``evidence_path``
    citation) or by ``verify_round`` (one per lineage event detected
    across rounds).
    """

    agent_name: str
    round: int
    claim_id: str
    evidence_path: str
    status: LedgerStatus
    file_path: str | None = None
    line_range: tuple[int, int] | None = None
    snippet: str | None = None
    notes: str = ""
    # Set when this entry represents a lineage event rather than a per-claim
    # citation. ``lineage_flag`` is mutually exclusive with the file/snippet
    # fields above.
    lineage_flag: LineageFlag | None = None
    lineage_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "round": self.round,
            "claim_id": self.claim_id,
            "evidence_path": self.evidence_path,
            "status": self.status,
            "file_path": self.file_path,
            "line_range": list(self.line_range) if self.line_range else None,
            "snippet": self.snippet,
            "notes": self.notes,
            "lineage_flag": self.lineage_flag,
            "lineage_detail": self.lineage_detail,
        }


@dataclass
class VerifierLedger:
    """Append-only collection of ``LedgerEntry`` items across all rounds.

    Used as both the in-state representation (carried by the LangGraph
    state dict) and the persisted ``verifier_ledger.json`` shape.
    """

    entries: list[LedgerEntry] = field(default_factory=list)

    def extend(self, more: list[LedgerEntry]) -> None:
        self.entries.extend(more)

    def entries_for_claim(self, claim_id: str, agent_name: str) -> list[LedgerEntry]:
        return [e for e in self.entries if e.claim_id == claim_id and e.agent_name == agent_name]

    def latest_round_entries(self, round_num: int) -> list[LedgerEntry]:
        return [e for e in self.entries if e.round == round_num]

    def latest_round(self) -> int | None:
        """Return the highest round number present in the ledger, or None
        when the ledger is empty.
        """
        if not self.entries:
            return None
        return max(e.round for e in self.entries)

    def has_unverified_in_round(self, round_num: int) -> bool:
        """True if any non-lineage entry in this round failed verification.

        Lineage flags are checked separately by ``has_lineage_flag_in_round``.
        """
        for e in self.latest_round_entries(round_num):
            if e.lineage_flag is not None:
                continue
            if e.status != "verified":
                return True
        return False

    def has_lineage_flag_in_round(self, round_num: int) -> bool:
        return any(e.lineage_flag is not None for e in self.latest_round_entries(round_num))

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}


# ---------------------------------------------------------------------------
# evidence_path parsing
# ---------------------------------------------------------------------------


# Match `file_path:line[-line]` — the dominant citation shape in our schemas.
# file_path can include dots, slashes, dashes, underscores. No spaces.
_FILE_LINE_RE = re.compile(r"^(?P<path>[\w./\-]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
# Match `file_path#section` — used for doc citations like `plan.md#step-4`.
_FILE_SECTION_RE = re.compile(r"^(?P<path>[\w./\-]+)#(?P<section>[\w\-_]+)$")
# Match bare `file_path` (no line range, no section).
_BARE_PATH_RE = re.compile(r"^(?P<path>[\w./\-]+\.\w+)$")


@dataclass(frozen=True)
class ParsedCitation:
    """One parsed reference from an ``evidence_path`` string."""

    raw: str
    file_path: str | None
    line_range: tuple[int, int] | None
    section: str | None
    parseable: bool

    @classmethod
    def unparseable(cls, raw: str) -> ParsedCitation:
        return cls(raw=raw, file_path=None, line_range=None, section=None, parseable=False)


def parse_evidence_path(evidence_path: str) -> list[ParsedCitation]:
    """Parse a multi-citation ``evidence_path`` string into citations.

    Splits on ``;`` (the convention agents use for multiple citations) and
    tries the file:line, file#section, and bare-file patterns. Pieces that
    don't match any pattern become ``unparseable`` entries — they still get
    a ledger row so the citation isn't silently lost.
    """
    citations: list[ParsedCitation] = []
    if not evidence_path or not evidence_path.strip():
        citations.append(ParsedCitation.unparseable(""))
        return citations

    for piece in evidence_path.split(";"):
        piece = piece.strip()
        if not piece:
            continue

        if m := _FILE_LINE_RE.match(piece):
            start = int(m.group("start"))
            end = int(m.group("end")) if m.group("end") else start
            citations.append(
                ParsedCitation(
                    raw=piece,
                    file_path=m.group("path"),
                    line_range=(start, end),
                    section=None,
                    parseable=True,
                )
            )
            continue

        if m := _FILE_SECTION_RE.match(piece):
            citations.append(
                ParsedCitation(
                    raw=piece,
                    file_path=m.group("path"),
                    line_range=None,
                    section=m.group("section"),
                    parseable=True,
                )
            )
            continue

        if m := _BARE_PATH_RE.match(piece):
            citations.append(
                ParsedCitation(
                    raw=piece,
                    file_path=m.group("path"),
                    line_range=None,
                    section=None,
                    parseable=True,
                )
            )
            continue

        citations.append(ParsedCitation.unparseable(piece))

    if not citations:
        citations.append(ParsedCitation.unparseable(evidence_path))
    return citations


# ---------------------------------------------------------------------------
# Per-citation resolution + snippet attachment
# ---------------------------------------------------------------------------


_SNIPPET_CONTEXT_LINES = 2  # 2 lines above + 2 below + the cited range


def _resolve_path(workspace_path: str, file_path: str) -> Path | None:
    """Try resolving ``file_path`` relative to the workspace, then absolute.

    Returns the first ``Path`` that exists as a file, or ``None``.
    """
    candidates = [
        Path(workspace_path) / file_path,
        Path(file_path),
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _extract_snippet(
    path: Path, line_range: tuple[int, int] | None
) -> tuple[str | None, str]:
    """Read ``path`` and return ``(snippet, notes)``.

    When ``line_range`` is provided, extracts ±``_SNIPPET_CONTEXT_LINES``
    around the cited range. When omitted, returns the first 20 lines as a
    pointer (file-only citation).
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return None, f"read_error: {exc}"

    total = len(lines)
    if line_range is None:
        snippet_lines = lines[:20]
        notes = f"no line_range cited; first 20 lines of {total}"
    else:
        start, end = line_range
        if start < 1 or end < start:
            return None, f"invalid_range: start={start} end={end}"
        if end > total:
            return None, f"line_range_out_of_bounds: end={end} > file_lines={total}"
        snip_start = max(1, start - _SNIPPET_CONTEXT_LINES)
        snip_end = min(total, end + _SNIPPET_CONTEXT_LINES)
        snippet_lines = lines[snip_start - 1 : snip_end]
        notes = f"resolved lines {start}-{end} with ±{_SNIPPET_CONTEXT_LINES} context"

    return "\n".join(snippet_lines), notes


def _verify_one_citation(
    citation: ParsedCitation,
    workspace_path: str,
    agent_name: str,
    round_num: int,
    claim_id: str,
) -> LedgerEntry:
    """Verify a single parsed citation and return its ledger entry."""
    if not citation.parseable:
        return LedgerEntry(
            agent_name=agent_name,
            round=round_num,
            claim_id=claim_id,
            evidence_path=citation.raw,
            status="unparseable_evidence",
            notes=f"could not parse {citation.raw!r} as file:line, file#section, or bare path",
        )

    assert citation.file_path is not None
    resolved = _resolve_path(workspace_path, citation.file_path)
    if resolved is None:
        return LedgerEntry(
            agent_name=agent_name,
            round=round_num,
            claim_id=claim_id,
            evidence_path=citation.raw,
            status="file_not_found",
            file_path=citation.file_path,
            line_range=citation.line_range,
            notes=f"path {citation.file_path!r} does not resolve relative to workspace or absolute",
        )

    snippet, notes = _extract_snippet(resolved, citation.line_range)
    if snippet is None:
        return LedgerEntry(
            agent_name=agent_name,
            round=round_num,
            claim_id=claim_id,
            evidence_path=citation.raw,
            status="unresolved_path",
            file_path=str(resolved),
            line_range=citation.line_range,
            notes=notes,
        )

    return LedgerEntry(
        agent_name=agent_name,
        round=round_num,
        claim_id=claim_id,
        evidence_path=citation.raw,
        status="verified",
        file_path=str(resolved),
        line_range=citation.line_range,
        snippet=snippet,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Position-level verification
# ---------------------------------------------------------------------------


def verify_position(position: dict[str, Any], workspace_path: str) -> list[LedgerEntry]:
    """Verify every cited ``evidence_path`` in a Position dict.

    Walks ``position["claims"]`` and ``position["disagreed_with_peer"]`` (both
    carry ``evidence_path`` per the schema). Emits one ledger entry per
    parsed citation; a multi-citation ``evidence_path`` like
    ``"file_a.py:10-20; file_b.py:30"`` produces two entries with the same
    ``claim_id`` and ``agent_name``.
    """
    agent_name = position.get("agent_name", "?")
    round_num = int(position.get("round", 0))
    entries: list[LedgerEntry] = []

    for claim in position.get("claims") or []:
        claim_id = claim.get("claim_id", "?")
        evidence_path = claim.get("evidence_path", "")
        for citation in parse_evidence_path(evidence_path):
            entries.append(
                _verify_one_citation(
                    citation, workspace_path, agent_name, round_num, claim_id
                )
            )

    for disagreement in position.get("disagreed_with_peer") or []:
        # Disagreement evidence_paths get a synthetic claim_id so they show
        # up in the ledger but don't collide with the agent's own claim_ids.
        peer_claim_id = disagreement.get("peer_claim_id", "?")
        synthetic_id = f"disagreement_against_{peer_claim_id}"
        evidence_path = disagreement.get("evidence_path", "")
        for citation in parse_evidence_path(evidence_path):
            entries.append(
                _verify_one_citation(
                    citation, workspace_path, agent_name, round_num, synthetic_id
                )
            )

    return entries


# ---------------------------------------------------------------------------
# Cross-round lineage tracking
# ---------------------------------------------------------------------------


def _claims_by_id(position: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c.get("claim_id", "?"): c for c in (position.get("claims") or [])}


def _detect_silent_rename(
    prior: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Return list of ``(old_id, new_id, claim_text_excerpt)`` tuples.

    A silent rename = same claim text in a different ``claim_id``. We compare
    the first 80 chars of ``claim`` text as the equivalence key; trailing
    edits to a claim wouldn't get flagged as renames (intentional — the
    point is to catch IDs swapped wholesale).
    """
    prior_text_to_id = {
        (c.get("claim") or "")[:80]: cid for cid, c in prior.items()
    }
    renames: list[tuple[str, str, str]] = []
    for cid, c in current.items():
        text = (c.get("claim") or "")[:80]
        if not text:
            continue
        if cid in prior:
            continue  # ID survived; this is a normal revision, not a rename
        old_id = prior_text_to_id.get(text)
        if old_id is not None and old_id != cid:
            renames.append((old_id, cid, text))
    return renames


def _detect_silent_retire(
    prior: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    renames: list[tuple[str, str, str]],
) -> list[str]:
    """Return list of claim_ids present in prior but absent in current.

    Excludes IDs that participated in a detected rename — those aren't
    retired, they were re-keyed.
    """
    renamed_old = {old for old, _new, _text in renames}
    return [cid for cid in prior if cid not in current and cid not in renamed_old]


def _detect_fabricated_peer_refs(
    own_position: dict[str, Any],
    peer_position: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    """Return list of ``(reference_type, fabricated_id)`` tuples.

    A fabricated peer reference is one of:
    - ``agreed_with_peer`` entry whose ID doesn't match any peer claim_id
    - ``disagreed_with_peer[*].peer_claim_id`` that doesn't match any peer claim_id
    """
    if peer_position is None:
        return []
    peer_ids = {c.get("claim_id", "?") for c in (peer_position.get("claims") or [])}
    fabricated: list[tuple[str, str]] = []
    for ref in own_position.get("agreed_with_peer") or []:
        if ref not in peer_ids:
            fabricated.append(("agreed_with_peer", ref))
    for dis in own_position.get("disagreed_with_peer") or []:
        peer_id = dis.get("peer_claim_id", "?")
        if peer_id not in peer_ids:
            fabricated.append(("disagreed_with_peer", peer_id))
    return fabricated


def _lineage_entries(
    agent_name: str,
    round_num: int,
    own_prior: dict[str, Any] | None,
    own_current: dict[str, Any],
    peer_prior: dict[str, Any] | None,
) -> list[LedgerEntry]:
    """Emit lineage ledger entries for one agent at one round."""
    entries: list[LedgerEntry] = []

    if own_prior is not None:
        prior_claims = _claims_by_id(own_prior)
        current_claims = _claims_by_id(own_current)
        renames = _detect_silent_rename(prior_claims, current_claims)
        for old_id, new_id, text in renames:
            entries.append(
                LedgerEntry(
                    agent_name=agent_name,
                    round=round_num,
                    claim_id=new_id,
                    evidence_path="",
                    status="content_mismatch_warning",
                    lineage_flag="silent_rename",
                    lineage_detail=(
                        f"claim_id {old_id!r} (round {own_prior.get('round','?')}) "
                        f"appears to be renamed to {new_id!r} (same text prefix: {text!r})"
                    ),
                )
            )
        for retired_id in _detect_silent_retire(prior_claims, current_claims, renames):
            entries.append(
                LedgerEntry(
                    agent_name=agent_name,
                    round=round_num,
                    claim_id=retired_id,
                    evidence_path="",
                    status="content_mismatch_warning",
                    lineage_flag="silent_retire",
                    lineage_detail=(
                        f"claim_id {retired_id!r} was present in round "
                        f"{own_prior.get('round','?')} but absent in this round "
                        "with no rename match — silently retired"
                    ),
                )
            )

    for ref_type, fabricated_id in _detect_fabricated_peer_refs(own_current, peer_prior):
        entries.append(
            LedgerEntry(
                agent_name=agent_name,
                round=round_num,
                claim_id=fabricated_id,
                evidence_path="",
                status="content_mismatch_warning",
                lineage_flag="fabricated_peer_ref",
                lineage_detail=(
                    f"{ref_type} references peer claim_id {fabricated_id!r} "
                    f"but peer's latest position has no such claim_id"
                ),
            )
        )

    return entries


def verify_round(
    latest_positions: dict[str, dict[str, Any]],
    prior_positions_by_agent: dict[str, dict[str, Any]],
    prior_ledger: VerifierLedger,
    round_num: int,
    workspace_path: str,
) -> VerifierLedger:
    """Verify a full round's worth of positions and extend the ledger.

    Args:
        latest_positions: ``{agent_name: position_dict}`` for the current round.
        prior_positions_by_agent: ``{agent_name: position_dict}`` for the
            previous round (or empty when round_num == 1).
        prior_ledger: ledger entries from rounds 1..round_num-1.
        round_num: 1-indexed current round.
        workspace_path: absolute path used for resolving citations.
    """
    new_entries: list[LedgerEntry] = []

    # Per-citation verification.
    for position in latest_positions.values():
        new_entries.extend(verify_position(position, workspace_path))

    # Cross-round lineage tracking. Build a quick map of agent → peer name
    # so each agent's fabricated_peer_ref check uses the right peer Position.
    agent_names = list(latest_positions)
    peer_of: dict[str, str | None] = {}
    for name in agent_names:
        peer_candidates = [n for n in agent_names if n != name]
        peer_of[name] = peer_candidates[0] if peer_candidates else None

    for agent_name, current_position in latest_positions.items():
        own_prior = prior_positions_by_agent.get(agent_name)
        peer_name = peer_of.get(agent_name)
        peer_prior = latest_positions.get(peer_name) if peer_name else None
        new_entries.extend(
            _lineage_entries(
                agent_name=agent_name,
                round_num=round_num,
                own_prior=own_prior,
                own_current=current_position,
                peer_prior=peer_prior,
            )
        )

    extended = VerifierLedger(entries=list(prior_ledger.entries))
    extended.extend(new_entries)
    return extended


__all__ = [
    "LedgerStatus",
    "LineageFlag",
    "LedgerEntry",
    "VerifierLedger",
    "ParsedCitation",
    "parse_evidence_path",
    "verify_position",
    "verify_round",
]
