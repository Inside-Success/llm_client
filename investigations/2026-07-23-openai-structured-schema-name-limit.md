# OpenAI structured-schema name limit

## Atoms

| ID | Question | Dependencies | Status |
| --- | --- | --- | --- |
| A1 | Where did the hosted Deep request fail? | none | answered |
| A2 | Which shared-client request field caused the provider rejection? | A1 | answered |
| A3 | Which call paths can emit the same invalid field? | A2 | answered |
| A4 | What is the smallest general repair? | A2, A3 | answered |

## Evidence and answers

### A1

Render trace `digimon.query.6d9e081466984ec499cfbc027f8155b2`
completed representation selection, graph retrieval, and source retrieval, then
failed in DIGIMON's final coverage judgment. The provider returned HTTP 400:
`text.format.name` had length 70 while the maximum is 64.

### A2

`llm_client/execution/structured_runtime.py` sends
`response_model.__name__` as the native JSON-schema name. The failing name was
generated from a dynamic Pydantic coverage-envelope class, so application code
cannot assume class names remain under the provider limit.

### A3

The same unsized name is emitted by the synchronous and asynchronous Responses
paths and by both native-schema Completions paths. Repairing only the observed
asynchronous Responses call would leave three equivalent failure mechanisms.

### A4

Derive one provider-safe name centrally. Preserve names of 64 characters or
less verbatim. For longer names, retain a readable prefix and append a
deterministic SHA-256 suffix so distinct long names with the same prefix do not
collapse.

## Contraction

The failure is not a DIGIMON scheduling or model-quality problem. It is one
shared transport-field invariant applied inconsistently at four provider
dispatch sites; a single helper plus four call-site substitutions covers the
observed path and its inverse sync/Completions paths.

## Assumptions register

| # | Assumption | Confidence | How to verify | Round | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | OpenAI enforces a 64-character schema-name ceiling. | high | Retained provider error from the hosted trace. | 1 | verified |
| 2 | A deterministic shortened name is transport metadata and does not change local validation. | high | Focused unit tests plus a real structured call. | 1 | verified |
| 3 | The current failure is reproducible on the deployed revision. | high | Hosted trace and Render traceback. | 1 | verified |

## Synthesis

**Root cause:** the shared runtime forwarded an unbounded dynamic Pydantic class
name into OpenAI's bounded `text.format.name` field.

**Impact:** a valid Deep retrieval could spend time and complete evidence
collection, then fail before returning coverage.

**Recommendation:** centralize deterministic schema-name bounding in
`structured_runtime.py`, apply it to all four native structured transports, and
rerun the exact hosted Deep request.

**Confidence:** high. The provider named the rejected field and the traceback
identifies the exact final coverage call.

**Open question:** none for this bounded repair; broader provider naming
character constraints are outside the reproduced failure.
