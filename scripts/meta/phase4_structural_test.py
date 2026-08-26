"""Third candidate: detect the *shape* of atomic-claim verification.

Not field names — structure: a list-valued property whose item model carries an
enum-typed verdict field alongside a substantial free-text field.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

DB = "file:/home/brian/projects/data/llm_observability.db?mode=ro"
SAMPLE = 25000
MAX_SNAPSHOT = 400_000
JUDGE_TASK = re.compile(r"judge|review|critic|eval|score|grade|audit|verif", re.I)


def resolve(node, defs, depth=0):
    if not isinstance(node, dict) or depth > 6:
        return node if isinstance(node, dict) else {}
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return resolve(defs.get(ref.split("/")[-1], {}), defs, depth + 1)
    for key in ("anyOf", "allOf", "oneOf"):
        options = node.get(key)
        if isinstance(options, list):
            for option in options:
                got = resolve(option, defs, depth + 1)
                if got.get("properties") or got.get("enum"):
                    return got
    return node


def looks_like_claim_verification(schema: dict) -> bool:
    defs = schema.get("$defs") or schema.get("definitions") or {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False
    for spec in props.values():
        spec = resolve(spec, defs)
        if spec.get("type") != "array":
            continue
        item = resolve(spec.get("items") or {}, defs)
        item_props = item.get("properties")
        if not isinstance(item_props, dict) or len(item_props) < 3:
            continue
        has_enum = False
        has_text = False
        for field_spec in item_props.values():
            resolved = resolve(field_spec, defs)
            if resolved.get("enum") or resolved.get("const") is not None:
                has_enum = True
            if resolved.get("type") == "string" and not resolved.get("enum"):
                has_text = True
        if has_enum and has_text:
            return True
    return False


conn = sqlite3.connect(DB, uri=True)
cur = conn.execute(
    "select task, schema_hash, call_snapshot from llm_calls "
    "where call_snapshot is not null and schema_hash is not null "
    "order by id desc limit ?",
    (SAMPLE,),
)

shapes, names, tasks_for = {}, {}, defaultdict(set)
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
        if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
            continue
        shapes[schema_hash] = schema
        names[schema_hash] = (req.get("response_model_fqn") or "?").split(".")[-1]
        tasks_for[schema_hash].add(task or "?")
    del batch

tp = fp = fn = tn = 0
fps, fns = [], []
for key, schema in shapes.items():
    predicted = looks_like_claim_verification(schema)
    actual = any(JUDGE_TASK.search(t) for t in tasks_for[key])
    row = (names[key], sorted(tasks_for[key])[:1])
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
print(f"STRUCTURAL detector over {total} distinct shapes:")
print(f"  true positives : {tp}")
print(f"  false positives: {fp}")
print(f"  false negatives: {fn}")
print(f"  true negatives : {tn}")
if tp + fp:
    print(f"  precision: {tp / (tp + fp):.2f}")
if tp + fn:
    print(f"  recall   : {tp / (tp + fn):.2f}")

print("\n--- does it catch the canonical judges? ---")
for key, schema in shapes.items():
    if names[key] in {
        "ClaimVerificationReport",
        "ConstrainedClaimVerificationReport",
        "CentralClaimEntailmentReviewForMechanismBoundEvidenceIds",
        "CentralClaimEntailmentReviewForSynthesisBoundEvidenceIds",
        "MechanismCritiqueResponse",
    }:
        print(f"  {names[key]:56s} detected={looks_like_claim_verification(schema)}")

print("\n--- sample FALSE POSITIVES ---")
for name, tasks in fps[:10]:
    print(f"  {name:40s} task={tasks}")
