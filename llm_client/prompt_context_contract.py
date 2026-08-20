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
class PromptContextContract:
    """Declared context budget for one prompt template."""

    source: Path
    variables: dict[str, VariableBudget]
    allow_undeclared: bool

    def violations(self, context: dict[str, Any]) -> list[str]:
        """Report every breach for one render, ordered worst first.

        All breaches are reported rather than the first, so a caller fixing an
        oversized prompt sees the whole picture instead of discovering the next
        offender only after fixing this one.
        """

        breaches: list[tuple[float, str]] = []
        for name, value in context.items():
            budget = self.variables.get(name)
            if budget is None:
                if not self.allow_undeclared:
                    breaches.append(
                        (
                            float("inf"),
                            (
                                f"{name!r} is not declared in "
                                f"{self.source.name} (allow_undeclared is false)"
                            ),
                        )
                    )
                continue
            if budget.unbounded:
                continue
            size = _measured_bytes(value)
            if size > budget.max_bytes:
                ratio = size / budget.max_bytes
                breaches.append(
                    (
                        ratio,
                        (
                            f"{name!r} is {size:,} bytes, over its "
                            f"{budget.max_bytes:,} byte budget ({ratio:.1f}x)"
                        ),
                    )
                )
        breaches.sort(key=lambda item: item[0], reverse=True)
        return [message for _, message in breaches]


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

    breaches = contract.violations(context)
    if not breaches:
        return []

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
