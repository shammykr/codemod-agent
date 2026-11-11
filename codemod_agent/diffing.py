"""Unified diffs that ``git apply`` accepts."""

from __future__ import annotations

import difflib

NO_EOL = "\\ No newline at end of file\n"


def unified_diff(path: str, before: str, after: str) -> str:
    """Return a git-style unified diff for one file (paths relative to the repo root)."""
    if before == after:
        return ""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    out = [f"diff --git a/{path} b/{path}\n"]
    for line in lines:
        out.append(line if line.endswith("\n") else line + "\n" + NO_EOL)
    return "".join(out)


def combine(diffs: list[str]) -> str:
    return "".join(d for d in diffs if d)
