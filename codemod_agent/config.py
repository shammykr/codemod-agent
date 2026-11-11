"""YAML configuration (codemod.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from codemod_agent.models import Severity

DEFAULT_CONFIG_NAME = "codemod.yaml"


@dataclass
class LLMConfig:
    provider: str = "mock"  # "mock" | "openai"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    timeout: float = 60.0


@dataclass
class AnalysisConfig:
    tracked_only: bool = True
    exclude: list[str] = field(default_factory=list)
    disabled_rules: list[str] = field(default_factory=list)
    min_severity: Severity = Severity.LOW


@dataclass
class BuildConfig:
    test_command: str | None = None
    timeout: float = 600.0


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    build: BuildConfig = field(default_factory=BuildConfig)


def _merge[T](obj: T, data: dict[str, Any] | None) -> T:
    if not data:
        return obj
    known = {f.name for f in fields(obj)}  # type: ignore[arg-type]
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
    for key, value in data.items():
        setattr(obj, key, value)
    return obj


def load_config(path: Path | None, project_dir: Path) -> Config:
    """Load ``path`` or ``<project_dir>/codemod.yaml`` if present; else defaults."""
    if path is None:
        candidate = project_dir / DEFAULT_CONFIG_NAME
        path = candidate if candidate.exists() else None
    cfg = Config()
    if path is None:
        return cfg
    raw = yaml.safe_load(path.read_text()) or {}
    _merge(cfg.llm, raw.get("llm"))
    _merge(cfg.analysis, raw.get("analysis"))
    _merge(cfg.build, raw.get("build"))
    cfg.analysis.min_severity = Severity(cfg.analysis.min_severity)
    return cfg
