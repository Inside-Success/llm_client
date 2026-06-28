"""Deliberation CLI subcommand.

Symmetric N-agent debate via ``python -m llm_client deliberate-task``. Pairs
with the duet's ``duet-review`` but uses a different topology — both agents
form independent positions, exchange them, iterate until convergence or
round-cap.

Usage::

    python -m llm_client deliberate-task \\
        --task-file question.json \\
        --workspace /abs/path/to/repo \\
        --out runs/my-debate \\
        --agents agent_a:codex/gpt-5.4,agent_b:claude-code/opus \\
        --max-rounds 3 \\
        --synthesis-model claude-code/opus

The task file is JSON or YAML with at minimum ``task_id``, ``title``,
``question``. Optional: ``success_criteria`` (list), ``constraints`` (list),
``extra`` (dict for profile-specific params).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _parse_agents(raw: str) -> list[tuple[str, str]]:
    """Parse ``--agents`` flag value into ``[(name, model), ...]``.

    Format: ``"name1:model1,name2:model2"``. Whitespace trimmed.
    Raises ``ValueError`` if any entry is malformed.
    """
    pairs: list[tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"Bad --agents entry {entry!r}; expected 'name:model'"
            )
        name, _, model = entry.partition(":")
        name = name.strip()
        model = model.strip()
        if not name or not model:
            raise ValueError(
                f"Bad --agents entry {entry!r}; name and model both required"
            )
        pairs.append((name, model))
    if len(pairs) != 2:
        raise ValueError(
            f"--agents must list exactly 2 entries for v1; got {len(pairs)}. "
            "Format: 'name1:model1,name2:model2'."
        )
    return pairs


def _load_task_file(path: Path) -> dict[str, Any]:
    """Load a task file (JSON or YAML by extension)."""
    if not path.is_file():
        print(f"error: --task-file not found: {path}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            print(
                "error: --task-file is YAML but pyyaml is not installed. "
                "Use a .json file or `pip install pyyaml`.",
                file=sys.stderr,
            )
            sys.exit(2)
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        print(
            f"error: --task-file {path} must contain a JSON/YAML object, "
            f"got {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(2)
    return data


def cmd_deliberate_task(args: argparse.Namespace) -> None:
    """Execute the ``deliberate-task`` subcommand.

    Loads the task file, parses ``--agents``, builds and runs the
    deliberation LangGraph workflow. Outputs per-round position artifacts
    plus a synthesis and signoff to ``--out``.
    """
    # Side-effect import: registers built-in profiles before lookup.
    import llm_client.workflow.profiles  # noqa: F401
    from llm_client.workflow.deliberate import build_deliberation_workflow

    workspace = str(Path(args.workspace).resolve())
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    task_data = _load_task_file(Path(args.task_file))
    # workspace_path on the task is overwritten by the CLI flag.
    task_data["workspace_path"] = workspace

    try:
        agents = _parse_agents(args.agents) if args.agents else None
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    app, initial_state = build_deliberation_workflow(
        run_dir=str(out_dir),
        task=task_data,
        trace_id=args.trace_id or task_data.get("task_id", "deliberate-task"),
        max_budget=args.max_budget,
        agents=agents,
        max_rounds=args.max_rounds,
        synthesis_model=args.synthesis_model,
    )

    print(
        f"=== deliberate-task ({task_data.get('task_id', '?')}) ===",
        flush=True,
    )
    print(f"  agents: {agents or 'default(codex/gpt-5.4,claude-code/opus)'}")
    print(f"  max_rounds: {args.max_rounds}")
    print(f"  synthesis_model: {args.synthesis_model or 'claude-code/opus (default)'}")
    print()

    result = app.invoke(
        initial_state,
        config={"configurable": {"thread_id": task_data.get("task_id", "deliberate")}},
    )

    print(f"verdict: {result.get('final_verdict', 'unknown')}")
    print(f"total_rounds: {result.get('round', 0)}")
    print(f"\nArtifacts written to: {out_dir}")


def register_parser(subparsers: Any) -> None:
    """Register the ``deliberate-task`` subcommand on the CLI.

    Wires the argparse surface for symmetric N-agent debate. Mirrors the
    shape of the duet's ``register_parser`` so the two subcommands feel
    consistent at the command line.
    """
    p = subparsers.add_parser(
        "deliberate-task",
        help="Symmetric N-agent debate: two agents form independent positions and argue to convergence",
        description=(
            "Runs a symmetric deliberation between two coding agents. Each agent "
            "writes an independent Position on the task, then iteratively reads "
            "the peer's position and revises until convergence (rule-based) or "
            "max_rounds is hit. Writes per-round position artifacts plus a "
            "synthesis to --out. See docs/plans/33_deliberation_workflow.md for "
            "the design rationale and how this differs from `duet-review`."
        ),
    )
    p.add_argument(
        "--task-file",
        required=True,
        help="Path to a JSON or YAML file with task_id, title, question, optionally success_criteria, constraints, extra",
    )
    p.add_argument(
        "--workspace",
        required=True,
        help="Absolute path the agents treat as cwd (overwrites task.workspace_path)",
    )
    p.add_argument("--out", required=True, help="Output directory for run artifacts")
    p.add_argument(
        "--agents",
        help=(
            "Comma-separated agent assignments 'name1:model1,name2:model2'. "
            "Default: agent_a:codex/gpt-5.4,agent_b:claude-code/opus"
        ),
    )
    p.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Round cap; hitting this with residual disagreement promotes verdict to productive_disagreement (default: 3)",
    )
    p.add_argument(
        "--synthesis-model",
        help="Model for the synthesis stage. Default: claude-code/opus.",
    )
    p.add_argument(
        "--trace-id",
        help="Trace ID for observability. Defaults to task_id from the task file.",
    )
    p.add_argument(
        "--max-budget",
        type=float,
        default=8.0,
        help="USD budget for the entire run (default: 8.0; deliberation typically takes 4-8 LLM calls)",
    )
    p.set_defaults(handler=cmd_deliberate_task)
