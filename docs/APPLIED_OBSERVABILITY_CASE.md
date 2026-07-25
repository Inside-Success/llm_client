# LLM Client Applied Observability Case

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Portfolio Claim

LLM Client should not lead the portfolio as a standalone analyst artifact. Its value is engineering governance: every LLM call can carry task, trace, budget, provider, token, latency, cost, error, and structured-output metadata that downstream projects can use to make decisions.

## Applied Case Pattern

The best reviewer-facing case is any project where observability changed the engineering decision:

| Signal | Decision it should support |
|--------|----------------------------|
| Cost by task | Keep, remove, batch, or reroute expensive steps |
| Error breakdown | Fix schema, retry policy, prompt contract, or provider route |
| Trace replay | Identify which phase produced a bad downstream artifact |
| Structured-output validation | Decide whether the contract or the prompt needs repair |
| Latency by operation | Decide whether a workflow is usable interactively or only as batch |

## How To Present It

Frame LLM Client through applied systems:

1. AC15 uses governed execution to make code-generation benchmark runs inspectable.
2. Grounded Research uses traces and provenance to debug claim and dispute workflows.
3. Qualitative Coding uses structured output and evaluation hooks to avoid treating labels as evidence by default.

## Caveat

Infrastructure only becomes portfolio evidence when attached to an applied decision. Do not lead with API breadth; lead with one trace where the data changed what was built next.
