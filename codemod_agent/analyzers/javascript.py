"""JavaScript analyzer using lightweight regex/pattern scanning."""

from __future__ import annotations

import re
from collections import Counter

from codemod_agent.analyzers.base import LanguageAnalyzer
from codemod_agent.models import FileInventory, Finding
from codemod_agent.rules import make_finding

REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
IMPORT_RE = re.compile(r"""^\s*import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""", re.M)
MEMBER_CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*\(")
LINE_COMMENT_RE = re.compile(r"(^|[^:])//.*$", re.M)
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(source: str) -> str:
    """Blank out comments while preserving line numbers."""
    source = BLOCK_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), source)
    return LINE_COMMENT_RE.sub(r"\1", source)


class JavaScriptAnalyzer(LanguageAnalyzer):
    language = "javascript"
    extensions = (".js", ".mjs", ".cjs")

    def scan(self, path: str, source: str) -> FileInventory:
        code = strip_comments(source)
        imports = set(REQUIRE_RE.findall(code)) | set(IMPORT_RE.findall(code))
        calls = Counter(MEMBER_CALL_RE.findall(code))
        return FileInventory(
            path=path,
            language=self.language,
            imports=sorted(imports),
            api_calls=dict(calls.most_common()),
        )

    def detect(self, path: str, source: str) -> list[Finding]:
        lines = source.splitlines(keepends=True)
        code_lines = mask_strings(strip_comments(source)).splitlines()
        findings: list[Finding] = []
        for lineno, code in enumerate(code_lines, start=1):
            for rule, pattern, message in JS_PATTERNS:
                for m in pattern.finditer(code):
                    target = lines[lineno - 1][m.start() : m.end()]
                    findings.append(
                        make_finding(rule, path, lines, lineno, lineno, target, message)
                    )
        return findings


STRING_RE = re.compile(r"""(['"`])(?:\\.|(?!\1).)*\1""")

JS_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("JS001", re.compile(r"\bvar\s+"), "'var' is function-scoped and hoisted."),
    # `x == null` is the accepted idiom for null-or-undefined, so it is not flagged.
    (
        "JS002",
        re.compile(r"(?<![=!<>])(?:==|!=)(?!=)(?!\s*(?:null|undefined)\b)"),
        "Loose equality coerces operand types.",
    ),
    ("JS003", re.compile(r"\bnew\s+Buffer\s*\("), "The Buffer() constructor is unsafe."),
    ("JS004", re.compile(r"\butil\.isArray\s*\("), "util.isArray is deprecated."),
    (
        "JS005",
        re.compile(r"\b(?:fs\.exists|url\.parse|crypto\.createCipher)\s*\("),
        "This Node.js API is deprecated.",
    ),
]


def mask_strings(code: str) -> str:
    """Replace string-literal contents with spaces so patterns don't match inside them."""
    return STRING_RE.sub(lambda m: m.group(1) + " " * (len(m.group(0)) - 2) + m.group(1), code)
