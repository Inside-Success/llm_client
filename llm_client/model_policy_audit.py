"""Audit repos for raw model literals and llm_client policy bypasses."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

CODE_EXTENSIONS = {
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
}

DOC_DIR_NAMES = {
    "docs",
    "investigations",
}

TEST_DIR_NAMES = {
    "tests",
    "testdata",
    "fixtures",
}

LOW_SIGNAL_DIR_NAMES = {
    "archive",
    "PROJECTS_DEFERRED",
    "worktrees",
    "deprecated",
}

ALLOW_LINE_TOKENS = (
    "model-policy: allow-raw-model",
)

MODEL_OVERRIDE_FIELD_RE = re.compile(
    r"\b(?:override_model|fallback_model|fallback_models|benchmark_model)\b"
)

BANNED_MODEL_PATTERNS = frozenset({"fable", "gpt-5.5", "gpt-5.4-mini"})

DIRECT_PROVIDER_IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"import\s+(?P<import_module>"
    r"openai|anthropic|litellm|cohere|mistralai|groq|ollama|"
    r"google\.generativeai|google\.genai"
    r")(?:\s|,|$)"
    r"|from\s+(?P<from_module>"
    r"openai|anthropic|litellm|cohere|mistralai|groq|ollama|"
    r"google\.generativeai|google\.genai|"
    r"langchain_openai|langchain_anthropic|"
    r"llama_index\.llms\.openai|llama_index\.llms\.anthropic"
    r")\s+import\b"
    r"|from\s+google\s+import\s+genai\b"
    r")"
)

DIRECT_PROVIDER_CALL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bopenai\.(?:ChatCompletion\.create|Completion\.create|chat\.completions\.create)\s*\("
        ),
        "openai",
    ),
    (re.compile(r"\banthropic\.(?:Anthropic|AsyncAnthropic)\s*\("), "anthropic"),
    (re.compile(r"\blitellm\.a?completion\s*\("), "litellm"),
    (
        re.compile(r"\b(?:google\.)?genai\.(?:Client|GenerativeModel)\s*\("),
        "google.genai",
    ),
    (re.compile(r"\bChatOpenAI\s*\("), "langchain_openai"),
    (re.compile(r"\bChatAnthropic\s*\("), "langchain_anthropic"),
)

DEFAULT_MODEL_IDS = frozenset(
    {
        "openrouter/minimax/minimax-m3",
        "minimax/minimax-m3",
        "minimax-m3",
    }
)

CALL_RE = re.compile(
    r"\b(?:a?call_llm(?:_structured|_with_tools|_batch)?|stream_llm|astream_llm)"
    r"\(\s*(['\"])(?P<model>[^'\"]+)\1"
)

MODEL_LITERAL_RE = re.compile(
    r"(['\"])(?P<model>[^'\"]+)\1"
)


class PolicyViolation(BaseModel):
    path: str
    line: int
    kind: str
    model: str
    text: str


def _looks_like_model_id(value: str) -> bool:
    lower = value.lower()
    provider_prefixes = (
        "openrouter/",
        "openai/",
        "anthropic/",
        "deepseek/",
        "gemini/",
        "google/",
        "inception/",
        "ollama/",
        "qwen/",
        "x-ai/",
        "z-ai/",
        "codex/",
        "claude-code/",
        "minimax/",
    )
    bare_prefixes = (
        "gpt-",
        "gemini-",
        "claude-",
        "grok-",
        "deepseek-",
        "minimax-",
        "o1-",
        "o3-",
    )
    if any(lower.startswith(prefix) and len(lower) > len(prefix) for prefix in provider_prefixes):
        return True
    return lower.startswith(bare_prefixes)


def _is_default_model_id(value: str) -> bool:
    """Return whether a literal names the current ecosystem default model."""

    return value.strip().lower() in DEFAULT_MODEL_IDS


def _is_banned_model_id(value: str) -> bool:
    """Return whether a model literal is denied regardless of override metadata."""

    lower = value.strip().lower()
    return any(pattern in lower for pattern in BANNED_MODEL_PATTERNS)


def _has_override_acceptance(lines: list[str]) -> bool:
    """Return whether a file records human acceptance for model overrides.

    The scanner is intentionally conservative: an override record must be
    explicit and include who accepted it and why. Expiry and richer provenance
    can be added by consumer policy without weakening this base check.
    """

    joined = "\n".join(lines)
    return (
        "model_override_acceptance" in joined
        and "accepted_by" in joined
        and "reason" in joined
    )


def _has_registration_exception(lines: list[str]) -> bool:
    """Return whether a file records a reviewed llm_client registration exception."""

    joined = "\n".join(lines)
    return (
        "llm_client_registration_exception" in joined
        and "accepted_by" in joined
        and "reason" in joined
        and "category" in joined
    )


def _direct_provider_reference(code_segment: str) -> str | None:
    """Return the direct provider SDK reference in a Python code segment."""

    import_match = DIRECT_PROVIDER_IMPORT_RE.search(code_segment)
    if import_match:
        if import_match.group("import_module"):
            return import_match.group("import_module")
        if import_match.group("from_module"):
            return import_match.group("from_module")
        return "google.genai"

    for pattern, provider in DIRECT_PROVIDER_CALL_PATTERNS:
        if pattern.search(code_segment):
            return provider
    return None


def _should_skip_file(
    path: Path,
    *,
    include_docs: bool,
    include_tests: bool,
) -> bool:
    parts = set(path.parts)
    if path.suffix not in CODE_EXTENSIONS:
        return True
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if not include_docs and parts & DOC_DIR_NAMES:
        return True
    if not include_tests and parts & TEST_DIR_NAMES:
        return True
    if parts & LOW_SIGNAL_DIR_NAMES:
        return True
    return False


def _iter_candidate_files(
    roots: Iterable[Path],
    *,
    include_docs: bool,
    include_tests: bool,
) -> Iterable[Path]:
    for root in roots:
        if root.is_file():
            if not _should_skip_file(root, include_docs=include_docs, include_tests=include_tests):
                yield root
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip_file(path, include_docs=include_docs, include_tests=include_tests):
                continue
            yield path


def scan_paths(
    roots: Iterable[Path],
    *,
    include_docs: bool = False,
    include_tests: bool = False,
    require_llm_client: bool = False,
    registration_only: bool = False,
) -> list[PolicyViolation]:
    """Scan paths for model-policy violations.

    ``registration_only`` is the fast path for cross-workspace llm_client
    adoption audits: it checks only production Python files for direct provider
    SDK usage and intentionally skips raw model literal scanning.
    """

    if registration_only:
        require_llm_client = True

    violations: list[PolicyViolation] = []
    for path in _iter_candidate_files(
        roots,
        include_docs=include_docs,
        include_tests=include_tests,
    ):
        if registration_only and path.suffix != ".py":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        has_override_acceptance = _has_override_acceptance(lines)
        has_registration_exception = _has_registration_exception(lines)
        for line_no, line in enumerate(lines, start=1):
            if any(token in line for token in ALLOW_LINE_TOKENS):
                continue
            code_segment = line.split("#", 1)[0]
            stripped = code_segment.strip()
            if not stripped:
                continue
            if (
                require_llm_client
                and path.suffix == ".py"
                and not has_registration_exception
            ):
                provider = _direct_provider_reference(code_segment)
                if provider is not None:
                    violations.append(
                        PolicyViolation(
                            path=str(path),
                            line=line_no,
                            kind="direct_provider_sdk",
                            model=provider,
                            text=stripped,
                        )
                    )
                    continue
            if registration_only:
                continue
            call_match = CALL_RE.search(code_segment)
            if call_match and _looks_like_model_id(call_match.group("model")):
                model = call_match.group("model")
                if _is_banned_model_id(model):
                    violations.append(
                        PolicyViolation(
                            path=str(path),
                            line=line_no,
                            kind="banned_model_literal",
                            model=model,
                            text=stripped,
                        )
                    )
                    continue
                if _is_default_model_id(model):
                    continue
                if has_override_acceptance:
                    continue
                violations.append(
                    PolicyViolation(
                        path=str(path),
                        line=line_no,
                        kind="direct_call_literal",
                        model=model,
                        text=stripped,
                    )
                )
                continue
            for literal_match in MODEL_LITERAL_RE.finditer(code_segment):
                model = literal_match.group("model")
                if not _looks_like_model_id(model):
                    continue
                if _is_banned_model_id(model):
                    violations.append(
                        PolicyViolation(
                            path=str(path),
                            line=line_no,
                            kind="banned_model_literal",
                            model=model,
                            text=stripped,
                        )
                    )
                    break
                if _is_default_model_id(model):
                    continue
                if has_override_acceptance:
                    continue
                violation_kind = (
                    "unaccepted_model_override"
                    if MODEL_OVERRIDE_FIELD_RE.search(code_segment)
                    else "raw_model_literal"
                )
                violations.append(
                    PolicyViolation(
                        path=str(path),
                        line=line_no,
                        kind=violation_kind,
                        model=model,
                        text=stripped,
                    )
                )
                break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Repo paths to audit")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on violations")
    parser.add_argument("--include-docs", action="store_true", help="Scan docs/investigations")
    parser.add_argument("--include-tests", action="store_true", help="Scan tests and fixtures")
    parser.add_argument(
        "--require-llm-client",
        action="store_true",
        help="Flag direct provider SDK usage unless a registration exception is recorded",
    )
    parser.add_argument(
        "--registration-only",
        action="store_true",
        help="Fast path: only audit direct provider SDK registration, not raw model literals",
    )
    args = parser.parse_args(argv)

    roots = [Path(item).resolve() for item in args.paths]
    violations = scan_paths(
        roots,
        include_docs=args.include_docs,
        include_tests=args.include_tests,
        require_llm_client=args.require_llm_client,
        registration_only=args.registration_only,
    )
    if not violations:
        print("MODEL POLICY OK")
        return 0

    print("MODEL POLICY VIOLATIONS")
    for violation in violations:
        print(
            f"{violation.path}:{violation.line}: {violation.kind}: "
            f"{violation.model} :: {violation.text}"
        )
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
