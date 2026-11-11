"""Prompt construction and response parsing for change generation."""

from __future__ import annotations

import json
import re

from codemod_agent.llm.base import ChangeRequest, Suggestion

SYSTEM_PROMPT = """\
You are a code modernization assistant. You receive one finding from a static analyzer
together with the exact source lines it refers to and surrounding context.
Rewrite ONLY the given lines to apply the recommended change. Preserve indentation,
behaviour and comments. Do not touch code outside the given lines.
Respond with a single JSON object and nothing else:
{"replacement": "<rewritten lines>", "imports": ["<import line needed>", ...],
 "explanation": "<one sentence>"}
If the change cannot be made safely, respond with {"replacement": null}."""


def build_user_prompt(req: ChangeRequest) -> str:
    f = req.finding
    return (
        f"File: {f.file} ({req.language})\n"
        f"Rule: {f.rule} - {f.title}\n"
        f"Finding: {f.message}\n"
        f"Recommended change: {f.recommendation}\n"
        f"Matched expression: {f.target}\n\n"
        f"--- context before ---\n{req.context_before}"
        f"--- lines to rewrite (lines {f.line}-{f.end_line}) ---\n{f.snippet}"
        f"--- context after ---\n{req.context_after}"
    )


FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_response(text: str) -> Suggestion | None:
    """Parse the model's JSON reply, tolerating markdown code fences."""
    text = FENCE_RE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    replacement = data.get("replacement")
    if not isinstance(replacement, str):
        return None
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    imports = [str(i) for i in data.get("imports") or []]
    return Suggestion(replacement, imports, str(data.get("explanation", "")))
