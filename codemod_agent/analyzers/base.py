"""Analyzer interface. Add a new language by subclassing ``LanguageAnalyzer``."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from codemod_agent.models import FileInventory, Finding


class LanguageAnalyzer(ABC):
    language: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def scan(self, path: str, source: str) -> FileInventory:
        """Build the import / API-usage inventory for one file."""

    @abstractmethod
    def detect(self, path: str, source: str) -> list[Finding]:
        """Return modernization findings for one file (ids are assigned later)."""
