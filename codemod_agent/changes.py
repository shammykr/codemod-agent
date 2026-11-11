"""LLM-driven change generation and in-memory application of a single change."""

from __future__ import annotations

import ast

from codemod_agent.analyzers import analyzer_for
from codemod_agent.llm import ChangeRequest, LLMProvider
from codemod_agent.models import Change, Finding

CONTEXT_LINES = 8


def build_request(finding: Finding, content: str) -> ChangeRequest:
    """Assemble the prompt context for ``finding`` from the file's current content."""
    lines = content.splitlines(keepends=True)
    start = locate(lines, finding.snippet, finding.line)
    if start is None:
        start = finding.line - 1
    end = start + len(finding.snippet.splitlines())
    analyzer = analyzer_for(finding.file)
    return ChangeRequest(
        finding=finding,
        language=analyzer.language if analyzer else "text",
        context_before="".join(lines[max(0, start - CONTEXT_LINES) : start]),
        context_after="".join(lines[end : end + CONTEXT_LINES]),
    )


def generate_change(provider: LLMProvider, finding: Finding, content: str) -> Change | None:
    suggestion = provider.suggest(build_request(finding, content))
    if suggestion is None or suggestion.replacement == finding.snippet:
        return None
    return Change(
        finding_id=finding.id,
        rule=finding.rule,
        file=finding.file,
        line=finding.line,
        original=finding.snippet,
        replacement=suggestion.replacement,
        imports=suggestion.imports,
    )


def locate(lines: list[str], block: str, expected_line: int) -> int | None:
    """Find the 0-based start index of ``block`` in ``lines``, nearest to ``expected_line``."""
    block_lines = block.splitlines(keepends=True)
    n = len(block_lines)
    if n == 0:
        return None
    hits = [i for i in range(len(lines) - n + 1) if lines[i : i + n] == block_lines]
    if not hits:
        return None
    return min(hits, key=lambda i: abs(i - (expected_line - 1)))


def _add_python_imports(content: str, imports: list[str]) -> str:
    existing = {ln.strip() for ln in content.splitlines()}
    missing = [imp for imp in imports if imp.strip() not in existing]
    if not missing:
        return content
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content  # validation will reject the change anyway
    insert_at = 0
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        insert_at = body[0].end_lineno or 0  # after the module docstring
    for node in body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            insert_at = node.end_lineno or insert_at
    lines = content.splitlines(keepends=True)
    new = [imp.strip() + "\n" for imp in missing]
    return "".join(lines[:insert_at] + new + lines[insert_at:])


def apply_change(content: str, change: Change) -> str | None:
    """Apply ``change`` to ``content``; None if the original lines can no longer be found."""
    lines = content.splitlines(keepends=True)
    start = locate(lines, change.original, change.line)
    if start is None:
        return None
    end = start + len(change.original.splitlines())
    new = lines[:start] + change.replacement.splitlines(keepends=True) + lines[end:]
    result = "".join(new)
    if change.imports and change.file.endswith(".py"):
        result = _add_python_imports(result, change.imports)
    return result
