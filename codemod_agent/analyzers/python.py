"""Python analyzer built on the stdlib ``ast`` module."""

from __future__ import annotations

import ast
from collections import Counter

from codemod_agent.analyzers.base import LanguageAnalyzer
from codemod_agent.models import FileInventory


def dotted_name(node: ast.AST) -> str | None:
    """Return ``a.b.c`` for a Name/Attribute chain, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def import_aliases(tree: ast.Module) -> dict[str, str]:
    """Map local names to fully-qualified names (``np`` -> ``numpy``)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    base = aliases.get(head, head)
    return f"{base}.{rest}" if rest else base


class PythonAnalyzer(LanguageAnalyzer):
    language = "python"
    extensions = (".py",)

    def scan(self, path: str, source: str) -> FileInventory:
        inv = FileInventory(path=path, language=self.language)
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return inv
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        aliases = import_aliases(tree)
        calls: Counter[str] = Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = dotted_name(node.func)
                if name:
                    calls[resolve(name, aliases)] += 1
        inv.imports = sorted(set(imports))
        inv.api_calls = dict(calls.most_common())
        return inv
