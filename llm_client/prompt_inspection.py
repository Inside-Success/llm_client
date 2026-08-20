"""Find content that appears more than once inside one assembled prompt.

Sending the same bytes twice is pure waste: it costs tokens and money, and it
tells the model nothing it was not already told. It is also easy to do by
accident, because the duplication usually lives inside a data structure nobody
reads end to end.

The case this was built from: a review prompt carried a
``discriminator_audit_resolution`` artifact whose ``final_audit`` field was a
byte-identical copy of ``attempts[-1].audit`` - 1,076,211 characters sent twice
in a 3,014,303 character prompt, on every call that could see that artifact.

Why this walks the structure instead of scanning the text
---------------------------------------------------------

The obvious implementation is to slide a window over the rendered prompt and
look for repeated hashes. Measured against that real payload it finds **nothing**,
at any stride: the two copies sit at different nesting depths, so
``json.dumps(..., indent=2)`` indents them differently and the bytes never match
even though the data is identical. Text-level scanning cannot see this class of
duplication at all.

Parsing the value and hashing canonicalized subtrees finds it exactly, because
canonical serialization removes the indentation difference. The cost is that it
only works on values that parse as JSON. In practice that is most of them: every
context variable in the reference call site is a ``json.dumps`` result, covering
99.9% of that prompt by bytes.

Only the outermost duplication is reported. The real payload contains four
duplicated subtrees, but three are nested inside the first, and listing all of
them buries the finding that matters under its own consequences.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DUPLICATE_STRICT_ENV = "LLM_CLIENT_PROMPT_DUPLICATE_STRICT"

DEFAULT_MIN_DUPLICATE_BYTES = 10_000
"""Ignore small repeats.

Short repeated values are normal and meaningless - an id echoed in two places,
a shared enum, a repeated null. The threshold is about finding waste worth
acting on, not about structural purity.
"""


class DuplicateContentError(Exception):
    """The same large content was found more than once in one prompt."""


@dataclass(frozen=True)
class DuplicatedContent:
    """One piece of content reachable by more than one path."""

    size_bytes: int
    paths: tuple[str, ...]

    @property
    def wasted_bytes(self) -> int:
        """Bytes that carry no information the first copy did not already."""

        return self.size_bytes * (len(self.paths) - 1)

    def describe(self) -> str:
        joined = " == ".join(self.paths)
        return (
            f"{self.size_bytes:,} bytes appear {len(self.paths)} times "
            f"({self.wasted_bytes:,} wasted): {joined}"
        )


def _canonical(value: Any) -> str:
    """Serialize so that identical data compares equal regardless of layout."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _walk(value: Any, path: str) -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _walk(child, f"{path}/{escaped}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}/{index}")


def _is_nested_within(inner: str, outer: str) -> bool:
    return inner != outer and inner.startswith(outer + "/")


def find_duplicated_content(
    context: dict[str, Any],
    *,
    min_bytes: int = DEFAULT_MIN_DUPLICATE_BYTES,
) -> list[DuplicatedContent]:
    """Report content repeated across or within the values of one prompt.

    Values that do not parse as JSON are compared whole rather than walked, so a
    plain-text variable duplicated verbatim is still caught even though its
    interior is opaque.

    Findings are ordered by wasted bytes, worst first, and a duplication nested
    inside a larger one is suppressed.
    """

    by_digest: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}

    for name, raw in context.items():
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            walkable = True
        except (TypeError, ValueError):
            parsed, walkable = raw, False

        if not walkable:
            text = raw if isinstance(raw, str) else str(raw)
            if len(text.encode("utf-8")) < min_bytes:
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            by_digest.setdefault(digest, []).append(name)
            sizes[digest] = len(text.encode("utf-8"))
            continue

        for path, node in _walk(parsed, name):
            serialized = _canonical(node)
            size = len(serialized.encode("utf-8"))
            if size < min_bytes:
                continue
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            by_digest.setdefault(digest, []).append(path)
            sizes[digest] = size

    findings = [
        DuplicatedContent(size_bytes=sizes[digest], paths=tuple(paths))
        for digest, paths in by_digest.items()
        if len(paths) > 1
    ]
    findings.sort(key=lambda item: item.wasted_bytes, reverse=True)

    # Suppress a duplication that is merely a consequence of a larger one: if
    # every path of a finding sits inside some path of a bigger finding, it adds
    # nothing a reader did not already know.
    kept: list[DuplicatedContent] = []
    for finding in findings:
        if any(
            all(
                any(_is_nested_within(path, outer) for outer in bigger.paths)
                for path in finding.paths
            )
            for bigger in kept
        ):
            continue
        kept.append(finding)
    return kept


def extract_json_spans(text: str, *, min_bytes: int = DEFAULT_MIN_DUPLICATE_BYTES) -> list[Any]:
    """Recover the JSON values embedded in an already-rendered prompt.

    At render time the context variables are still separate values and can be
    walked directly. A *stored* prompt is one flat string, and text-level
    scanning cannot find duplication inside it - the copies are indented
    differently, so their bytes never match. Pulling the JSON back out restores
    the structure that makes the comparison possible, which is what lets a
    historical call be audited rather than only a live one.

    Only spans at least ``min_bytes`` long are returned; small inline objects
    are not where waste hides and parsing every brace is not worth the time.
    """

    decoder = json.JSONDecoder()
    found: list[Any] = []
    index = 0
    length = len(text)
    while index < length:
        candidates = [pos for pos in (text.find("{", index), text.find("[", index)) if pos != -1]
        if not candidates:
            break
        start = min(candidates)
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        if end - start >= min_bytes:
            found.append(value)
            index = end
        else:
            index = start + 1
    return found


def find_duplicated_content_in_text(
    text: str,
    *,
    min_bytes: int = DEFAULT_MIN_DUPLICATE_BYTES,
) -> list[DuplicatedContent]:
    """Find repeated content in a rendered prompt by recovering its JSON."""

    spans = extract_json_spans(text, min_bytes=min_bytes)
    if not spans:
        return []
    context = {f"json[{i}]": value for i, value in enumerate(spans)}
    return find_duplicated_content(context, min_bytes=min_bytes)


@dataclass(frozen=True)
class VariableSize:
    """How much of an assembled prompt one context variable accounts for."""

    name: str
    size_bytes: int
    share: float

    def describe(self) -> str:
        return f"{self.name}: {self.size_bytes:,} bytes ({self.share * 100:.1f}%)"


def summarize_context(context: dict[str, Any]) -> list[VariableSize]:
    """Attribute prompt size to the variables that produced it, largest first.

    Total prompt size was never the mystery - it is on every observability row
    as ``prompt_tokens``. What nothing recorded was *which variable owned the
    bytes*, and that is the number that tells you what to do about it. On the
    payload this was built from, one variable held 96.8% of the prompt while the
    evidence the task was actually about held 2.9%.

    Sizes are of the rendered values, so they sum to slightly less than the
    finished prompt, which also contains the template's own prose.
    """

    sizes = [
        VariableSize(
            name=name,
            size_bytes=len((value if isinstance(value, str) else str(value)).encode("utf-8")),
            share=0.0,
        )
        for name, value in context.items()
    ]
    total = sum(item.size_bytes for item in sizes)
    if total:
        sizes = [
            VariableSize(name=item.name, size_bytes=item.size_bytes, share=item.size_bytes / total)
            for item in sizes
        ]
    sizes.sort(key=lambda item: item.size_bytes, reverse=True)
    return sizes


def format_context_summary(sizes: list[VariableSize]) -> str:
    """Render a size attribution as an aligned table."""

    if not sizes:
        return "(no context variables)"
    width = max(len(item.name) for item in sizes)
    total = sum(item.size_bytes for item in sizes)
    lines = [f"{item.name:<{width}}  {item.size_bytes:>12,}  {item.share * 100:>5.1f}%" for item in sizes]
    lines.append(f"{'TOTAL':<{width}}  {total:>12,}  100.0%")
    return "\n".join(lines)


def duplicate_strict_mode() -> bool:
    """Whether duplicated content raises instead of warning.

    Opt-in only, and never inferred. Duplication is waste rather than
    incorrectness: the prompt still says everything it needs to, just twice.
    Failing a running pipeline over it would trade a cost problem for an
    availability problem.
    """

    return str(os.environ.get(DUPLICATE_STRICT_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def report_duplicated_content(
    context: dict[str, Any],
    *,
    label: str,
    min_bytes: int = DEFAULT_MIN_DUPLICATE_BYTES,
    strict: bool | None = None,
) -> list[DuplicatedContent]:
    """Warn, or raise in strict mode, when a prompt repeats large content."""

    findings = find_duplicated_content(context, min_bytes=min_bytes)
    if not findings:
        return findings

    total = sum(item.wasted_bytes for item in findings)
    detail = "; ".join(item.describe() for item in findings)
    message = (
        f"Duplicated content in {label}: {total:,} wasted bytes. {detail}. "
        "The same bytes twice cost tokens and tell the model nothing new; "
        "send one copy, or a reference to it."
    )
    if duplicate_strict_mode() if strict is None else strict:
        raise DuplicateContentError(message)
    logger.warning(message)
    return findings
