"""Fairer test: recurse into $defs so nested verdict fields are visible."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

DB = "file:/home/brian/projects/data/llm_observability.db?mode=ro"
SAMPLE = 25000
MAX_SNAPSHOT = 400_000

JUDGE_FIELDS = re.compile(
    r"^(disposition|verdict|score|severity|rating|judgment|judgement|grade|"
    r"assessment|entailment|correct|is_correct|passed|pass_fail|label|"
    r"decision|status|outcome)$",
    re.I,
)
JUDGE_TASK = re.compile(r"judge|review|critic|eval|score|grade|audit|verif", re.I)


def all_field_names(schema: dict) -> set[str]:
    """Every property name anywhere in the schema, including $defs."""
    found: set[str] = set()

    def walk(node, depth=0):
        if depth > 8 or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        props = node.get("properties")
        if isinstance(props, dict):
            found.update(props)
        for key, value in node.items():
            if key in {"properties", "$defs", "definitions", "items", "anyOf", "allOf", "oneOf"}:
                walk(value, depth + 1)

    walk(schema)
    return found


conn = sqlite3.connect(DB, uri=True)
cur = conn.execute(
    "select task, schema_hash, call_snapshot from llm_calls "
    "where call_snapshot is not null and schema_hash is not null "
    "order by id desc limit ?",
    (SAMPLE,),
)

shapes: dict[str, set[str]] = {}
names: dict[str, str] = {}
tasks_for: dict[str, set[str]] = defaultdict(set)

while True:
    batch = cur.fetchmany(200)
    if not batch:
        break
    for task, schema_hash, snap in batch:
        if not snap or len(snap) > MAX_SNAPSHOT:
            continue
        try:
            req = json.loads(snap).get("request", {})
        except Exception:
            continue
        schema = req.get("response_model_schema")
        if not isinstance(schema, dict):
            continue
        fields = all_field_names(schema)
        if not fields:
            continue
        shapes[schema_hash] = fields
        names[schema_hash] = (req.get("response_model_fqn") or "?").split(".")[-1]
        tasks_for[schema_hash].add(task or "?")
    del batch

tp = fp = fn = tn = 0
fps, fns = [], []
for key, fields in shapes.items():
    predicted = any(JUDGE_FIELDS.match(f) for f in fields)
    actual = any(JUDGE_TASK.search(t) for t in tasks_for[key])
    row = (names[key], sorted(f for f in fields if JUDGE_FIELDS.match(f))[:4], sorted(tasks_for[key])[:1])
    if predicted and actual:
        tp += 1
    elif predicted and not actual:
        fp += 1
        fps.append(row)
    elif not predicted and actual:
        fn += 1
        fns.append(row)
    else:
        tn += 1

total = tp + fp + fn + tn
print(f"NESTED heuristic (recurses $defs, broader vocabulary) over {total} distinct shapes:")
print(f"  true positives : {tp}")
print(f"  false positives: {fp}")
print(f"  false negatives: {fn}")
print(f"  true negatives : {tn}")
if tp + fp:
    print(f"  precision: {tp / (tp + fp):.2f}")
if tp + fn:
    print(f"  recall   : {tp / (tp + fn):.2f}")
print(f"\n  non-judge schemas that would be forced through a judging primitive: {fp}")
print("\n--- sample FALSE POSITIVES ---")
for name, hits, tasks in fps[:12]:
    print(f"  {name:36s} matched={hits} task={tasks}")
print("\n--- sample FALSE NEGATIVES ---")
for name, hits, tasks in fns[:8]:
    print(f"  {name:36s} matched={hits} task={tasks}")
