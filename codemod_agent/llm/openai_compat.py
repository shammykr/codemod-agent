"""Provider for any OpenAI-compatible /chat/completions endpoint (stdlib HTTP only)."""

from __future__ import annotations

import json
import os
import urllib.request

from codemod_agent.config import LLMConfig
from codemod_agent.llm.base import ChangeRequest, LLMProvider, Suggestion
from codemod_agent.llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_response


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.api_key = os.environ.get(cfg.api_key_env, "")
        if not self.api_key:
            raise RuntimeError(f"environment variable {cfg.api_key_env} is not set")

    def suggest(self, request: ChangeRequest) -> Suggestion | None:
        body = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
        }
        req = urllib.request.Request(
            self.cfg.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
            payload = json.load(resp)
        content = payload["choices"][0]["message"]["content"] or ""
        return parse_response(content)
