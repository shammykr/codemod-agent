"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from codemod_agent.models import Finding


@dataclass
class ChangeRequest:
    """Everything the model sees for one finding."""

    finding: Finding
    language: str
    context_before: str
    context_after: str


@dataclass
class Suggestion:
    replacement: str  # replaces finding.snippet (whole lines)
    imports: list[str] = field(default_factory=list)  # import lines the replacement needs
    explanation: str = ""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def suggest(self, request: ChangeRequest) -> Suggestion | None:
        """Return a replacement for ``request.finding.snippet`` or None if no safe change."""
