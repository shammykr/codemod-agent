"""JavaScript analyzer using lightweight regex/pattern scanning."""

from __future__ import annotations

import re
from collections import Counter

from codemod_agent.analyzers.base import LanguageAnalyzer
from codemod_agent.models import FileInventory

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
