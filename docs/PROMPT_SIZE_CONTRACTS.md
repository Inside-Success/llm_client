# Prompt Size Contracts

Three cooperating mechanisms that keep an LLM call's *input* from growing
without anyone noticing. They exist because the failure they catch is silent:
nothing errors, nothing looks broken, the payload just gets bigger every month.

## The failure this was built for

A structured review call was sending **615,835 prompt tokens** at **$0.31 a
call**, while the entire evidentiary corpus the analysis was about totalled
about **7,000 tokens**. One call carried roughly **50-90x the whole basis for
the analysis**, repeatedly, inside an iterative repair loop.

Two things about that case shaped the design:

**The call site already had an allowlist, and the offender was on it.** The
2.28MB artifact was explicitly permitted by name. It had not leaked past a
check; it had grown 100x inside one. A name-only contract would have
reproduced the bug in a tidier format, so every contract here carries a
**budget**, not just a list of permitted names.

**Cost hid the problem.** Prompt caching means a bigger payload can bill less.
On the same task and model, a 1,231,999-token call cost **$0.0276** (617,073
tokens cached) while a 615,835-token call cost **$0.3109** -- the call sending
twice as much looked 11x cheaper. Ranked by cost, the worst offender is
invisible. Everything here measures **prompt tokens**, never cost.

## Component A -- retrospective drift detection

```bash
make prompt-drift                      # last 7 days vs prior 30
make prompt-drift RECENT_DAYS=30 BASELINE_DAYS=60
python -m llm_client prompt-drift --json --fail-on-drift
```

Compares each `(project, task)` against **its own** history in the
observability database. Absolute thresholds do not transfer between tasks; a
200K-token prompt is routine for one and a 50x regression for another.

Two independent signals:

| Signal | Meaning |
|---|---|
| `prompt_growth` | recent median / baseline median exceeded the ratio -- a payload that grew and stayed grown |
| `prompt_dispersion` | recent p95 / recent median exceeded the ratio -- most calls normal, a subset enormous |

Dispersion is not redundant. In the reference case the median barely moved
while a subset of calls ran 50x higher on the same day; a median-only
comparison sees nothing.

This reads rows already recorded. No contract has to exist and no call site has
to change, so it covers the call sites that will never get a contract written.
It is also how you decide *which* call sites deserve one.

If the observability database cannot be read, this raises rather than
reporting "no drift" -- an unreadable database must not look like a clean bill
of health.

## Component B -- call-boundary ceiling

Measured inside `_prepare_public_call_envelope`, which already serializes the
messages to compute `prompt_sha256`; the check costs a `len()`, not a second
serialization.

```python
from llm_client.execution.call_contracts import register_task_prompt_budget

register_task_prompt_budget("myproject.review", 40_000)
```

Ceiling resolution: explicit `max_prompt_tokens=` on the call, then the value
registered for the `task`, then none. With no ceiling the payload is still
measured -- measurement is unconditional, enforcement is opt-in.

Ceilings are **registered by consumers**, not hard-coded here. `llm_client`
owns the mechanism; it does not carry any project's task names.

**Warn by default, strict on demand** (`LLM_CLIENT_PROMPT_SIZE_STRICT=1`, or
`CI`). These calls run inside long repair loops where hard-failing by default
would turn a cost problem into an availability problem.

The payload is **never truncated** to fit. Silently trimming a prompt would
change the model's inputs behind the caller's back.

Sizing is `len(serialized) // 4`, shared with `llm_client.agent.context_budget`.
Measured against one real payload it read 788,548 against a provider-reported
615,835 -- about 28% high on JSON-heavy content. That is fine for catching a
20x breach and useless as a billing figure; `prompt_tokens` on the
observability row remains the authority.

## Component C -- per-variable context budgets

Where the diagnosis actually lives. A template at `prompts/foo.yaml` is
governed by a sibling `prompts/foo.contract.yaml`:

```yaml
schema_version: "1.0"
allow_undeclared: false
variables:
  target_json:
    max_bytes: 10000
  evidence_json:
    max_bytes: 400000
  analysis_artifacts_json:
    max_bytes: 200000
```

`render_prompt()` checks the caller's context against it and names the
offender:

```
Prompt context contract violated for pass_central_claim_review.yaml:
'analysis_artifacts_json' is 2,917,684 bytes, over its 200,000 byte budget (14.6x)
```

**Attribution is the point.** Total prompt size was never a mystery --
`prompt_tokens` is on every observability row. What nothing recorded was *which
context variable owned the bytes*. On the real reference payload:

| variable | bytes | share of prompt |
|---|---|---|
| `analysis_artifacts_json` | 2,917,684 | **96.8%** |
| `evidence_json` | 87,830 | 2.9% |
| `claim_inventory_json` | 3,521 | 0.1% |
| `target_json` | 1,536 | 0.1% |
| template prose | 3,732 | 0.1% |

The unit is the **context variable**, not a field inside it. Call sites
routinely pass pre-serialized JSON (`analysis_artifacts_json=json.dumps(...)`),
so inner structure is not visible at render time and a field-level contract
could not be enforced without changing every consumer. Variable-level
budgeting is enforceable today and sufficient -- it names the offender.

A template with no contract file is unconstrained, so adoption is incremental.
A *malformed* contract raises: it must not silently degrade into "no
constraints". Strict mode is `LLM_CLIENT_PROMPT_CONTEXT_STRICT=1` or `CI`.

## Coverage limits

`_prepare_public_call_envelope` backs `call_llm`, `call_llm_structured`,
`acall_llm`, `acall_llm_structured`, and — transitively, since they delegate to
the public async entry points — all four batch functions.

It does **not** cover `call_llm_with_tools`, `stream_llm`,
`stream_llm_with_tools`, or their async variants; those build their own runtime
kwargs and never construct an envelope. Component B does not apply to them
today. Component C is unaffected, since it acts at `render_prompt`.
