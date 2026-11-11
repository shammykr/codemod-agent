"""LLM providers for change generation."""

from __future__ import annotations

from codemod_agent.config import LLMConfig
from codemod_agent.llm.base import ChangeRequest, LLMProvider, Suggestion
from codemod_agent.llm.mock import MockProvider
from codemod_agent.llm.openai_compat import OpenAICompatibleProvider


def get_provider(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "mock":
        return MockProvider()
    if cfg.provider == "openai":
        return OpenAICompatibleProvider(cfg)
    raise ValueError(f"unknown LLM provider: {cfg.provider!r}")


__all__ = ["ChangeRequest", "LLMProvider", "Suggestion", "get_provider"]
