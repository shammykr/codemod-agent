"""Structured validation: every generated file state is re-parsed before it is accepted."""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from codemod_agent.analyzers.dependencies import REQ_RE
from codemod_agent.analyzers.javascript import mask_strings, strip_comments

PAIRS = {")": "(", "]": "[", "}": "{"}


def validate_python(content: str) -> str | None:
    try:
        ast.parse(content)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return None


def validate_javascript(content: str, suffix: str = ".js") -> str | None:
    """Use ``node --check`` when Node is installed, else a delimiter-balance check."""
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as tmp:
            tmp.write(content)
        try:
            proc = subprocess.run(
                [node, "--check", tmp.name], capture_output=True, text=True, check=False
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        if proc.returncode != 0:
            msg = next((ln for ln in proc.stderr.splitlines() if "Error" in ln), "syntax error")
            return msg.strip()
        return None
    stack: list[str] = []
    for ch in mask_strings(strip_comments(content)):
        if ch in "([{":
            stack.append(ch)
        elif ch in PAIRS and (not stack or stack.pop() != PAIRS[ch]):
            return f"unbalanced '{ch}'"
    return f"unclosed '{stack[-1]}'" if stack else None


def validate_requirements(content: str) -> str | None:
    for i, raw in enumerate(content.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-") and not REQ_RE.fullmatch(line):
            return f"invalid requirement on line {i}: {line!r}"
    return None


def validate_json(content: str) -> str | None:
    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        return f"JSONDecodeError: {exc.msg} (line {exc.lineno})"
    return None


def validate(path: str, content: str) -> str | None:
    """Return an error message if ``content`` is not valid for ``path``'s type, else None."""
    if path.endswith(".py"):
        return validate_python(content)
    if path.endswith((".js", ".mjs", ".cjs")):
        return validate_javascript(content, Path(path).suffix)
    if path.endswith(".json"):
        return validate_json(content)
    if re.search(r"requirements[^/]*\.txt$", path):
        return validate_requirements(content)
    return None
