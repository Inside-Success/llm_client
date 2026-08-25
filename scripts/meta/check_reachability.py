#!/usr/bin/env python3
"""Module reachability sensor.

Answers one question: which modules in this repository are not reachable by
import from any declared entrypoint?

This is deliberately NOT vulture. Vulture asks whether a *symbol* is referenced
anywhere in the source text, which stays noisy inside a module nobody imports.
This asks whether a *module* is reachable, which is the measurement that catches
accretion: work that was completed, committed, and then never wired to anything.

Config lives in meta-process.yaml under `quality.reachability`:

    quality:
      reachability:
        enabled: true
        packages: [src/dodaf_modeler, workbench]
        entrypoints: [workbench/app.py, scripts/*.py]
        dynamic: [some.module.loaded.by.string]
        baseline: reachability_baseline.json

`dynamic` exists because `importlib.import_module("x")` is invisible to static
analysis. Anything listed there is treated as reachable, and the reason belongs
in a comment next to it.

Exit codes: 0 within baseline, 1 regression (more unreachable than baseline),
2 configuration or usage error. Regression is the ratchet: the count may fall
freely and may never rise.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, must be loud
    print("ERROR: PyYAML is required for the reachability sensor.", file=sys.stderr)
    sys.exit(2)


@dataclass
class Report:
    """Two measurements, because they answer different questions.

    `unreachable` is orphaned: nothing at all imports it, so it can be deleted
    on its own. That is the safe ratchet.

    `product_unreachable` is reachable from something, but not from the
    product. Those modules are held alive by their own script or their own
    test, which is why they look load-bearing locally and accumulate anyway.
    Retiring one means retiring its script and test together, so this is a
    tracked share rather than a hard gate.
    """

    passed: bool
    unreachable_count: int
    baseline_count: int
    total_modules: int
    unreachable_lines: int
    total_lines: int
    unreachable: list[str] = field(default_factory=list)
    newly_unreachable: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    product_unreachable_count: int = 0
    product_unreachable_lines: int = 0
    product_entrypoints: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def live_share(self) -> float:
        return 0.0 if not self.total_lines else 1 - self.unreachable_lines / self.total_lines

    @property
    def product_share(self) -> float:
        if not self.total_lines:
            return 0.0
        return 1 - self.product_unreachable_lines / self.total_lines


def _load_config(root: Path) -> dict[str, Any]:
    path = root / "meta-process.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    quality = data.get("quality") or data.get("meta_process", {}).get("quality", {})
    return (quality or {}).get("reachability", {}) or {}


def _module_name(path: Path, root: Path, package_roots: list[Path]) -> str | None:
    """Map a file to its importable dotted name, or None if not importable."""
    for pkg in package_roots:
        try:
            rel = path.relative_to(pkg.parent)
        except ValueError:
            continue
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) if parts else None
    return None


def _imports(path: Path, module: str, is_init: bool) -> list[str]:
    """Dotted names imported by this file, including `from x import y` targets."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = module.split(".")
                if is_init:
                    parts.append("_")  # __init__ addresses its own package
                base = ".".join(parts[: len(parts) - node.level])
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            found.append(target)
            # `from pkg import mod` - the name may itself be a module.
            found += [f"{target}.{alias.name}" for alias in node.names]
    return found


def analyse(root: Path, config: dict[str, Any]) -> Report:
    package_roots = [root / p for p in config.get("packages", [])]
    missing = [str(p) for p in package_roots if not p.is_dir()]
    if not package_roots or missing:
        return Report(
            False, 0, 0, 0, 0, 0,
            error=f"configured packages not found: {missing or 'none configured'}",
        )

    all_files = sorted(
        {f for pkg in package_roots for f in pkg.rglob("*.py")}
    )
    by_module: dict[str, Path] = {}
    for file in all_files:
        name = _module_name(file, root, package_roots)
        if name:
            by_module.setdefault(name, file)

    def collect(patterns: list[str]) -> list[Path]:
        found: list[Path] = []
        for pattern in patterns:
            found.extend(
                f for f in sorted(root.glob(pattern)) if f.suffix == ".py" and f.is_file()
            )
        return found

    def walk(entry_files: list[Path]) -> set[Path]:
        seeds: list[tuple[str, Path]] = []
        for file in entry_files:
            name = _module_name(file, root, package_roots)
            # A script outside the packages is still a valid root: walk its
            # imports without treating the script itself as a package module.
            seeds.append((name or f"__entry__{file.stem}", file))
        for dotted in config.get("dynamic", []):
            if dotted in by_module:
                seeds.append((dotted, by_module[dotted]))

        seen: dict[str, Path] = {}
        stack = list(seeds)
        while stack:
            module, path = stack.pop()
            if module in seen:
                continue
            seen[module] = path
            for target in _imports(path, module, path.name == "__init__.py"):
                if target in by_module and target not in seen:
                    stack.append((target, by_module[target]))

        hit = {p.resolve() for p in seen.values()}
        # A package's __init__.py executes whenever any of its submodules is
        # imported, so it is reachable if anything under it is.
        for module, path in by_module.items():
            if path.name != "__init__.py" or path.resolve() in hit:
                continue
            prefix = f"{module}." if module else ""
            if any(other.startswith(prefix) for other in seen):
                hit.add(path.resolve())
        return hit

    entry_files = collect(config.get("entrypoints", []))
    product_files = collect(config.get("product_entrypoints", []))
    reached = walk(entry_files)
    product_reached = walk(product_files) if product_files else reached

    def lines(path: Path) -> int:
        try:
            return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            return 0

    ignore = config.get("ignore", [])
    unreachable = [
        str(f.relative_to(root))
        for f in all_files
        if f.resolve() not in reached
        and not any(fnmatch.fnmatch(str(f.relative_to(root)), pat) for pat in ignore)
    ]
    unreachable_lines = sum(lines(root / rel) for rel in unreachable)
    product_unreachable = [
        f for f in all_files
        if f.resolve() not in product_reached
        and not any(fnmatch.fnmatch(str(f.relative_to(root)), pat) for pat in ignore)
    ]

    return Report(
        passed=True,
        unreachable_count=len(unreachable),
        baseline_count=0,
        total_modules=len(all_files),
        unreachable_lines=unreachable_lines,
        total_lines=sum(lines(f) for f in all_files),
        unreachable=sorted(unreachable),
        entrypoints=[str(f.relative_to(root)) for f in entry_files],
        product_unreachable_count=len(product_unreachable),
        product_unreachable_lines=sum(lines(f) for f in product_unreachable),
        product_entrypoints=[str(f.relative_to(root)) for f in product_files],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", type=Path)
    parser.add_argument("--check", action="store_true", help="fail on regression")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    config = _load_config(root)
    if not config.get("enabled"):
        print("reachability: disabled in meta-process.yaml")
        return 0

    report = analyse(root, config)
    if report.error:
        print(f"ERROR: {report.error}", file=sys.stderr)
        return 2

    baseline_path = root / config.get("baseline", "reachability_baseline.json")
    baseline: dict[str, Any] = {}
    if baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    known = set(baseline.get("unreachable", []))
    report.baseline_count = len(known)
    report.newly_unreachable = sorted(set(report.unreachable) - known)

    if args.write_baseline:
        baseline_path.write_text(
            json.dumps(
                {
                    "note": "Ratchet baseline. This count may fall, never rise.",
                    "unreachable_count": report.unreachable_count,
                    "product_share": round(report.product_share, 4),
                    "unreachable": report.unreachable,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"reachability: baseline written with {report.unreachable_count} modules")
        return 0

    if args.json:
        print(json.dumps(asdict(report), indent=2))
        return 0

    print(
        f"reachability: {report.total_modules - report.unreachable_count}"
        f"/{report.total_modules} modules reachable from "
        f"{len(report.entrypoints)} entrypoints "
        f"({report.live_share:.1%} of lines live)"
    )
    if report.product_entrypoints:
        baseline_share = baseline.get("product_share")
        drift = (
            f" (baseline {baseline_share:.1%})"
            if isinstance(baseline_share, float)
            else ""
        )
        print(
            f"  product path: {report.product_share:.1%} of lines reachable from "
            f"{len(report.product_entrypoints)} product entrypoint(s){drift}; "
            f"{report.product_unreachable_count} module(s) are held alive only by "
            "scripts or tests"
        )
    if report.newly_unreachable:
        print(
            f"\n{len(report.newly_unreachable)} module(s) became unreachable "
            "since the baseline:"
        )
        for name in report.newly_unreachable:
            print(f"  {name}")
        print(
            "\nWire it to an entrypoint, delete it, or - if it is imported by "
            "string - add it to quality.reachability.dynamic in meta-process.yaml "
            "with a comment saying why."
        )
        if args.check:
            return 1
    elif report.unreachable_count < report.baseline_count:
        print(
            f"reachability: {report.baseline_count - report.unreachable_count} "
            "module(s) retired since baseline. Run --write-baseline to lower the ratchet."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
