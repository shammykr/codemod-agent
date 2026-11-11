"""Language analyzer registry."""

from __future__ import annotations

from codemod_agent.analyzers.base import LanguageAnalyzer
from codemod_agent.analyzers.javascript import JavaScriptAnalyzer
from codemod_agent.analyzers.python import PythonAnalyzer

ANALYZERS: list[LanguageAnalyzer] = [PythonAnalyzer(), JavaScriptAnalyzer()]


def analyzer_for(path: str) -> LanguageAnalyzer | None:
    for analyzer in ANALYZERS:
        if path.endswith(analyzer.extensions):
            return analyzer
    return None


__all__ = ["ANALYZERS", "LanguageAnalyzer", "analyzer_for"]
