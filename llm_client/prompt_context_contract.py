"""Per-variable context budgets for prompt templates.

Component C of the prompt-size contract stack, and the only piece that answers
*which context variable* is responsible for an oversized prompt.

Motivation, from the case this was built against: a review call was sending
~615,000 prompt tokens while the entire evidentiary corpus the analysis was
about totalled ~7,000. The call site already had a hand-written allowlist of
permitted artifacts -- and the 2.28MB offender was *on* it. The artifact had
not leaked past a name check; it had grown 100x inside one. Name-only contracts
do not catch that, so this contract is budget-bearing per variable.

The unit of enforcement is the **context variable** passed to
``render_prompt``, not a field inside it. Call sites routinely hand in
pre-serialized JSON (``analysis_artifacts_json=json.dumps(...)``), so inner
field structure is not visible here and a field-level contract could not be
enforced without changing every consumer. Variable-level budgeting is both
enforceable today and sufficient: it names ``analysis_artifacts_json`` as the
2.28MB offender, which is exactly the attribution that was missing.

Contract files sit beside the template they govern: a template at
``prompts/foo.yaml`` is governed by ``prompts/foo.contract.yaml``. A template
with no contract file is unconstrained, so adoption is incremental.

Format::

    schema_version: "1.0"
    allow_undeclared: false
    variables:
      evidence_json:
        max_bytes: 400000
      analysis_artifacts_json:
        max_bytes: 200000
"""

from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

PROMPT_CONTEXT_STRICT_ENV = "LLM_CLIENT_PROMPT_CONTEXT_STRICT"

CONTRACT_SUFFIX = ".contract.yaml"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})


def prompt_context_strict_mode() -> bool:
    """Whether a contract breach raises instead of warning.

    Opt-in through one explicit environment variable, never inferred from
    ``CI`` or any other ambient signal. A context budget is a statement about
    input size, so the same correct code can satisfy it on one document and
    breach it on a longer one; making that fatal wherever ``CI`` happens to be
    set turns a large input into an opaque build failure. See
    ``llm_client.execution.call_contracts.prompt_size_strict_mode`` for the
    full reasoning.
    """

    value = str(os.environ.get(PROMPT_CONTEXT_STRICT_ENV, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


class PromptContextContractError(Exception):
    """A prompt context contract is malformed or was violated."""


@dataclass(frozen=True)
class VariableBudget:
    """Declared ceiling for one context variable.

    ``max_bytes`` is None when the variable is declared ``unbounded``. That is a
    positive statement, not a missing value: this variable carries content whose
    size is a property of the input, so a ceiling on it would fail on a long
    document and pass on a short one, which is the job working rather than a
    defect. Declaring it keeps it inside the contract, so it is reviewable and
    a genuinely new variable is still caught.
    """

    name: str
    max_bytes: int | None

    @property
    def unbounded(self) -> bool:
        return self.max_bytes is None


@dataclass(frozen=True)
class ContextBreach:
    """One context variable over its declared budget, or undeclared."""

    variable: str
    observed_bytes: int
    budget_bytes: int | None
    contract_name: str

    @property
    def undeclared(self) -> bool:
        """Whether the variable has no budget at all rather than an exceeded one."""

        return self.budget_bytes is None

    @property
    def severity(self) -> float:
        """How far over budget, for ordering. Undeclared sorts worst."""

        if self.budget_bytes is None:
            return float("inf")
        return self.observed_bytes / self.budget_bytes

    def describe(self) -> str:
        if self.budget_bytes is None:
            return (
                f"{self.variable!r} is not declared in "
                f"{self.contract_name} (allow_undeclared is false)"
            )
        return (
            f"{self.variable!r} is {self.observed_bytes:,} bytes, over its "
            f"{self.budget_bytes:,} byte budget ({self.severity:.1f}x)"
        )


@dataclass(frozen=True)
class PromptContextContract:
    """Declared context budget for one prompt template."""

    source: Path
    variables: dict[str, VariableBudget]
    allow_undeclared: bool

    def violation_records(self, context: dict[str, Any]) -> list[ContextBreach]:
        """Report every breach for one render as data, ordered worst first.

        All breaches are reported rather than the first, so a caller fixing an
        oversized prompt sees the whole picture instead of discovering the next
        offender only after fixing this one.

        Records rather than messages, because a breach is counted across a run
        as well as printed once. Aggregating parsed log strings is how a
        breached budget stays invisible.
        """

        breaches: list[ContextBreach] = []
        for name, value in context.items():
            budget = self.variables.get(name)
            if budget is None:
                if not self.allow_undeclared:
                    breaches.append(
                        ContextBreach(
                            variable=name,
                            observed_bytes=_measured_bytes(value),
                            budget_bytes=None,
                            contract_name=self.source.name,
                        )
                    )
                continue
            if budget.unbounded:
                continue
            size = _measured_bytes(value)
            if size > budget.max_bytes:
                breaches.append(
                    ContextBreach(
                        variable=name,
                        observed_bytes=size,
                        budget_bytes=budget.max_bytes,
                        contract_name=self.source.name,
                    )
                )
        breaches.sort(key=lambda breach: breach.severity, reverse=True)
        return breaches

    def violations(self, context: dict[str, Any]) -> list[str]:
        """Human-readable form of :meth:`violation_records`, worst first."""

        return [breach.describe() for breach in self.violation_records(context)]


def _measured_bytes(value: Any) -> int:
    """Size of one context value as it will contribute to the prompt."""

    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(str(value).encode("utf-8"))


def contract_path_for(template_path: Path) -> Path:
    """Return the sibling contract path for a template."""

    return template_path.with_name(template_path.stem + CONTRACT_SUFFIX)


def load_contract(template_path: Path) -> PromptContextContract | None:
    """Load the contract governing a template, or None when none exists.

    A missing contract is not an error -- templates adopt contracts one at a
    time. A *malformed* contract is an error: a contract that cannot be parsed
    must not silently degrade into "no constraints".
    """

    path = contract_path_for(template_path)
    if not path.exists():
        return None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptContextContractError(f"malformed contract {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise PromptContextContractError(
            f"contract must be a mapping, got {type(raw).__name__}: {path}"
        )

    schema_version = str(raw.get("schema_version", "")).strip()
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise PromptContextContractError(
            f"unsupported schema_version {schema_version!r} in {path}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    raw_variables = raw.get("variables") or {}
    if not isinstance(raw_variables, dict):
        raise PromptContextContractError(
            f"'variables' must be a mapping in {path}"
        )

    variables: dict[str, VariableBudget] = {}
    for name, spec in raw_variables.items():
        if not isinstance(spec, dict):
            raise PromptContextContractError(
                f"variable {name!r} must map to a mapping in {path}"
            )
        unbounded = spec.get("unbounded", False)
        if not isinstance(unbounded, bool):
            raise PromptContextContractError(
                f"variable {name!r} has a non-boolean unbounded in {path}"
            )
        max_bytes = spec.get("max_bytes")
        # Exactly one of the two, so that an unbounded variable is always a
        # decision somebody wrote down rather than a budget somebody forgot.
        if unbounded and max_bytes is not None:
            raise PromptContextContractError(
                f"variable {name!r} declares both max_bytes and unbounded in {path}"
            )
        if unbounded:
            variables[str(name)] = VariableBudget(name=str(name), max_bytes=None)
            continue
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise PromptContextContractError(
                f"variable {name!r} needs a positive integer max_bytes, "
                f"or unbounded: true, in {path}"
            )
        variables[str(name)] = VariableBudget(name=str(name), max_bytes=max_bytes)

    allow_undeclared = raw.get("allow_undeclared", False)
    if not isinstance(allow_undeclared, bool):
        raise PromptContextContractError(
            f"'allow_undeclared' must be a boolean in {path}"
        )

    return PromptContextContract(
        source=path,
        variables=variables,
        allow_undeclared=allow_undeclared,
    )


def enforce_contract(
    template_path: Path,
    context: dict[str, Any],
    *,
    strict: bool,
) -> list[str]:
    """Check one render against its contract; warn or raise on breach.

    Returns the breach messages (empty when compliant) so callers and tests can
    assert on attribution rather than parsing log output.
    """

    contract = load_contract(template_path)
    if contract is None:
        return []

    records = contract.violation_records(context)
    _TALLY.record(template_path.name, records)
    if not records:
        return []

    breaches = [record.describe() for record in records]
    detail = "; ".join(breaches)
    message = (
        f"Prompt context contract violated for {template_path.name}: {detail}. "
        f"These are locally declared budgets in {template_path.stem}{CONTRACT_SUFFIX}, "
        f"not provider limits. Budget only context that should NOT grow with the "
        f"input; if an over-budget variable carries the source material itself, "
        f"the budget is wrong, not the input."
    )
    if strict:
        raise PromptContextContractError(message)
    logger.warning(message)
    return breaches


class _BreachTally:
    """Process-wide count of contract breaches, for one report at end of run.

    ``enforce_contract`` warns once per breaching render. That is the right
    behaviour at the moment of the breach and the wrong one as the only
    behaviour: a long run emits the warning among everything else it prints,
    and nobody reads the 45th copy. Measured on a real
    ``process_tracing.central_claim_review`` run, ``analysis_artifacts_json``
    was over its declared ceiling on 45 of 74 large calls, at up to 1.7x, and
    the drift was found months later by querying stored prompts rather than by
    anyone seeing a warning.

    So the warning stays and a count accumulates beside it, for a caller to
    print once at a point a human is actually looking. This deliberately holds
    process-global state: the thing being measured is a property of the run,
    not of any one render, and threading a counter through every call site is
    how the report would fail to exist.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._renders: dict[str, int] = defaultdict(int)
        self._breaching: dict[str, int] = defaultdict(int)
        self._worst: dict[tuple[str, str], ContextBreach] = {}

    def record(self, template_name: str, breaches: list[ContextBreach]) -> None:
        with self._lock:
            self._renders[template_name] += 1
            if not breaches:
                return
            self._breaching[template_name] += 1
            for breach in breaches:
                key = (template_name, breach.variable)
                seen = self._worst.get(key)
                if seen is None or breach.observed_bytes > seen.observed_bytes:
                    self._worst[key] = breach

    def reset(self) -> None:
        with self._lock:
            self._renders.clear()
            self._breaching.clear()
            self._worst.clear()

    def summary(self) -> list[TemplateBreachSummary]:
        with self._lock:
            return [
                TemplateBreachSummary(
                    template_name=name,
                    renders=self._renders[name],
                    breaching_renders=count,
                    worst=tuple(
                        breach
                        for (template, _), breach in sorted(self._worst.items())
                        if template == name
                    ),
                )
                for name, count in sorted(self._breaching.items())
                if count
            ]


@dataclass(frozen=True)
class TemplateBreachSummary:
    """What one template did to its budget over a whole run."""

    template_name: str
    renders: int
    breaching_renders: int
    worst: tuple[ContextBreach, ...]

    def describe(self) -> str:
        worst = "; ".join(breach.describe() for breach in self.worst)
        return (
            f"{self.template_name}: {self.breaching_renders} of {self.renders} "
            f"renders over budget. Worst seen - {worst}"
        )


_TALLY = _BreachTally()


def contract_breach_summary() -> list[TemplateBreachSummary]:
    """Per-template breach counts since process start or the last reset."""

    return _TALLY.summary()


def reset_contract_breach_tally() -> None:
    """Forget everything counted so far. For tests and for per-run scoping."""

    _TALLY.reset()


def format_contract_breach_summary() -> str | None:
    """One block a caller can print at end of run, or None when clean.

    ``None`` rather than "no breaches" so a caller can print this
    unconditionally without adding a line to every clean run - a summary that
    always prints something is a summary people stop reading.
    """

    summaries = contract_breach_summary()
    if not summaries:
        return None
    lines = ["prompt context contract breaches:"]
    lines.extend(f"  {summary.describe()}" for summary in summaries)
    return "\n".join(lines)
