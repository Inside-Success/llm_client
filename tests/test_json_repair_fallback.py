"""json_repair fallback + validation-authority move (2026-07-19).

litellm's in-call strict validation preempted llm_client's richer ladder:
fenced/near-JSON output raised inside acompletion, discarding usage and
forcing a full paid retry. Authority now lives in llm_client:
_robust_validate_json -> safe_json_loads -> json_repair last resort, with
Pydantic as the unchanged schema gate.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from llm_client.parsing_utils import safe_json_loads


class _Verdict(BaseModel):
    source_id: str
    verdict: str
    rationale: str = ""


class _Review(BaseModel):
    per_source: list[_Verdict]
    claim_supported_by_cited_set: bool


TRAILING_COMMA = """```json
{
  "per_source": [
    {"source_id": "S-1", "verdict": "supports", "rationale": "ok",}
  ],
  "claim_supported_by_cited_set": true
}
```"""

SINGLE_QUOTES = "{'per_source': [{'source_id': 'S-1', 'verdict': 'partial'}], 'claim_supported_by_cited_set': false}"

GARBAGE = "         \n\n         \n\n         "


class TestSafeJsonLoadsRepair:
    def test_trailing_comma_in_fences_repairs(self) -> None:
        data = safe_json_loads(TRAILING_COMMA)
        assert data["claim_supported_by_cited_set"] is True
        assert _Review.model_validate(data).per_source[0].source_id == "S-1"

    def test_single_quotes_repair(self) -> None:
        data = safe_json_loads(SINGLE_QUOTES)
        assert _Review.model_validate(data).per_source[0].verdict == "partial"

    def test_pure_garbage_still_raises(self) -> None:
        # The glm-5.2 blank-padding failure class must STILL fail loudly -
        # repair must never fabricate a payload out of whitespace.
        with pytest.raises(Exception):
            safe_json_loads(GARBAGE)

    def test_schema_gate_unchanged(self) -> None:
        # Repair fixes JSON syntax; Pydantic still rejects wrong shapes.
        data = safe_json_loads('{"per_source": "not-a-list", "claim_supported_by_cited_set": true}')
        with pytest.raises(ValidationError):
            _Review.model_validate(data)


class TestValidationAuthority:
    def test_litellm_in_call_validation_disabled(self) -> None:
        import llm_client  # noqa: F401 - triggers the module-level config
        import litellm

        assert litellm.enable_json_schema_validation is False
