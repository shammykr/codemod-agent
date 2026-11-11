"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Dependency:
    name: str
    version: str
    ecosystem: str  # "pypi" | "npm"
    manifest: str  # repo-relative path of the manifest file
    line: int


@dataclass
class FileInventory:
    path: str  # repo-relative path
    language: str
    imports: list[str] = field(default_factory=list)
    api_calls: dict[str, int] = field(default_factory=dict)


@dataclass
class Inventory:
    root: str
    git: dict[str, str] = field(default_factory=dict)
    files: list[FileInventory] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    id: str  # stable id, e.g. "F003"
    rule: str  # rule id, e.g. "PY002"
    title: str
    category: str  # deprecated-api | outdated-dependency | legacy-pattern
    severity: Severity
    file: str
    line: int
    end_line: int
    snippet: str  # full original source lines [line, end_line]
    target: str  # exact source segment the rule matched
    message: str
    recommendation: str
    autofix: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = str(self.severity)
        return d


@dataclass
class Change:
    finding_id: str
    rule: str
    file: str
    line: int
    original: str  # original lines (with newlines)
    replacement: str  # replacement lines (with newlines)
    imports: list[str] = field(default_factory=list)


@dataclass
class ChangeResult:
    finding_id: str
    rule: str
    file: str
    status: str  # applied | rejected-validation | rejected-tests | conflict | no-change | error
    detail: str = ""
    diff: str = ""
