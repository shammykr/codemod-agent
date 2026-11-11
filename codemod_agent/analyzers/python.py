"""Python analyzer built on the stdlib ``ast`` module."""

from __future__ import annotations

import ast
from collections import Counter

from codemod_agent.analyzers.base import LanguageAnalyzer
from codemod_agent.models import FileInventory, Finding
from codemod_agent.rules import make_finding


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

    def detect(self, path: str, source: str) -> list[Finding]:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return []
        visitor = _ModernizationVisitor(path, source, import_aliases(tree))
        visitor.visit(tree)
        return visitor.findings


OS_PATH_FUNCS = {
    "join",
    "exists",
    "isfile",
    "isdir",
    "basename",
    "dirname",
    "abspath",
    "getsize",
}
UNITTEST_ALIASES = {
    "assertEquals": "assertEqual",
    "assertNotEquals": "assertNotEqual",
    "assertAlmostEquals": "assertAlmostEqual",
    "assertNotAlmostEquals": "assertNotAlmostEqual",
    "assert_": "assertTrue",
    "failUnless": "assertTrue",
    "failIf": "assertFalse",
    "failUnlessEqual": "assertEqual",
    "assertRegexpMatches": "assertRegex",
    "assertNotRegexpMatches": "assertNotRegex",
    "assertRaisesRegexp": "assertRaisesRegex",
    "assertDictContainsSubset": "assertLessEqual",
}
PY2_BUILTINS = {"xrange": "range", "unicode": "str", "basestring": "str", "raw_input": "input"}
DEPRECATED_MODULES = {
    "imp": "importlib",
    "distutils": "setuptools / packaging",
    "asyncore": "asyncio",
    "asynchat": "asyncio",
    "cgi": "email.message / urllib.parse",
    "pipes": "shlex.quote",
    "telnetlib": "a third-party telnet library",
    "optparse": "argparse",
}


class _ModernizationVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str, aliases: dict[str, str]) -> None:
        self.path = path
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.aliases = aliases
        self.findings: list[Finding] = []

    def _add(self, rule: str, node: ast.AST, message: str, target: str | None = None) -> None:
        line = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", None) or line
        seg = target if target is not None else ast.get_source_segment(self.source, node) or ""
        self.findings.append(make_finding(rule, self.path, self.lines, line, end, seg, message))

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        if name:
            full = resolve(name, self.aliases)
            mod, _, func = full.rpartition(".")
            if mod == "os.path" and func in OS_PATH_FUNCS:
                self._add("PY001", node, f"{full}() can be expressed with pathlib.")
            elif full == "datetime.datetime.utcnow":
                self._add("PY010", node, "datetime.utcnow() returns a naive datetime.")
            elif full == "super" and len(node.args) == 2:
                self._add("PY005", node, "super() arguments are redundant in Python 3.")
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in UNITTEST_ALIASES and isinstance(node.func.value, ast.Name):
                self._add(
                    "PY003",
                    node,
                    f"{attr} is a removed alias of {UNITTEST_ALIASES[attr]}.",
                )
            elif attr == "has_key" and len(node.args) == 1:
                self._add("PY007", node, "has_key() was removed in Python 3.")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if (
            isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            self._add("PY002", node, "printf-style formatting is harder to read than f-strings.")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "object":
                header = self.lines[node.lineno - 1]
                self.findings.append(
                    make_finding(
                        "PY004",
                        self.path,
                        self.lines,
                        node.lineno,
                        node.lineno,
                        header.strip(),
                        f"class {node.name} inherits from object explicitly.",
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "__future__":
            names = [a.name for a in node.names if a.name != "annotations"]
            if names:
                self._add("PY006", node, f"__future__ imports {', '.join(names)} are no-ops.")
        elif node.module and node.module.split(".")[0] in DEPRECATED_MODULES:
            self._deprecated_module(node, node.module)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in DEPRECATED_MODULES:
                self._deprecated_module(node, alias.name)

    def _deprecated_module(self, node: ast.stmt, module: str) -> None:
        top = module.split(".")[0]
        self._add(
            "PY009",
            node,
            f"'{top}' is deprecated or removed; migrate to {DEPRECATED_MODULES[top]}.",
        )

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in PY2_BUILTINS and isinstance(node.ctx, ast.Load):
            self._add("PY008", node, f"{node.id} does not exist in Python 3.")
