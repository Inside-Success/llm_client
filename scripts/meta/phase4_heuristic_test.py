"""Is 'judge-shaped' detectable from a response schema, or is registration needed?

Streams real structured calls from the observability DB, extracts each distinct
response model's top-level field names, and asks whether a field-name heuristic
separates judging calls from non-judging ones.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

DB = "file:/home/brian/projects/data/llm_observability.db?mode=ro"
SAMPLE = 25000
MAX_SNAPSHOT = 400_000  # skip pathological blobs rather than load them

# The heuristic the handoff proposed: match judge-ish response field names.
JUDGE_FIELDS = re.compile(
    r"^(disposition|verdict|score|severity|rating|judgment|judgement|grade|"
    r"assessment|entailment|correct|is_correct|passed|pass_fail|label)$",
    re.I,
)
# Ground-truth proxy: the caller declared it as judging via the task tag.
JUDGE_TASK = re.compile(r"judge|review|critic|eval|score|grade|audit|verif", re.I)

conn = sqlite3.connect(DB, uri=True)
cur = conn.execute(
    """
    select task, schema_hash, call_snapshot
    from llm_calls
    where call_snapshot is not null and schema_hash is not null
    order by id desc limit ?
    """,
    (SAMPLE,),
)

shapes: dict[str, set[str]] = {}
names: dict[str, str] = {}
tasks_for: dict[str, set[str]] = defaultdict(set)
seen = kept = 0

while True:
    batch = cur.fetchmany(200)
    if not batch:
        break
    for task, schema_hash, snap in batch:
        seen += 1
        if not snap or len(snap) > MAX_SNAPSHOT:
            continue
        try:
            req = json.loads(snap).get("request", {})
        except Exception:
            continue
        schema = req.get("response_model_schema")
        if not isinstance(schema, dict):
            continue
        props = schema.get("properties")
        if not isinstance(props, dict):
            continue
        kept += 1
        key = schema_hash
        shapes[key] = set(props)
        names[key] = (req.get("response_model_fqn") or "?").split(".")[-1]
        tasks_for[key].add(task or "?")
    del batch

print(f"scanned calls: {seen:,}   with a recoverable response schema: {kept:,}")
print(f"distinct response shapes: {len(shapes)}")
print()

tp = fp = fn = tn = 0
false_positives, false_negatives = [], []
for key, props in shapes.items():
    predicted = any(JUDGE_FIELDS.match(p) for p in props)
    actual = any(JUDGE_TASK.search(t) for t in tasks_for[key])
    row = (names[key], sorted(props)[:6], sorted(tasks_for[key])[:2])
    if predicted and actual:
        tp += 1
    elif predicted and not actual:
        fp += 1
        false_positives.append(row)
    elif not predicted and actual:
        fn += 1
        false_negatives.append(row)
    else:
        tn += 1

total = tp + fp + fn + tn
print(f"field-name heuristic vs task-tag ground truth over {total} distinct shapes:")
print(f"  true positives : {tp}")
print(f"  false positives: {fp}   (non-judge schema that trips the heuristic)")
print(f"  false negatives: {fn}   (judging call the heuristic misses)")
print(f"  true negatives : {tn}")
if tp + fp:
    print(f"  precision: {tp / (tp + fp):.2f}")
if tp + fn:
    print(f"  recall   : {tp / (tp + fn):.2f}")

print("\n--- FALSE POSITIVES (would be wrongly forced through a judging primitive) ---")
for name, props, tasks in false_positives[:12]:
    print(f"  {name:34s} fields={props} tasks={tasks}")
print("\n--- FALSE NEGATIVES (judging that enforcement would not catch) ---")
for name, props, tasks in false_negatives[:12]:
    print(f"  {name:34s} fields={props} tasks={tasks}")
