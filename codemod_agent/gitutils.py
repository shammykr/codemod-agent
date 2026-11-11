"""Thin wrappers around the git CLI (via subprocess)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:  # git not installed
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def repo_root(path: Path) -> Path | None:
    """Return the top-level directory of the repository containing ``path``."""
    out = _git(["rev-parse", "--show-toplevel"], path)
    return Path(out.strip()).resolve() if out else None


def repo_metadata(root: Path) -> dict[str, str]:
    """Read branch / HEAD / remote information from the repository."""
    meta: dict[str, str] = {"root": str(root)}
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    head = _git(["rev-parse", "--short", "HEAD"], root)
    remote = _git(["config", "--get", "remote.origin.url"], root)
    if branch:
        meta["branch"] = branch.strip()
    if head:
        meta["head"] = head.strip()
    if remote:
        meta["remote"] = remote.strip()
    return meta


def tracked_files(path: Path) -> list[Path]:
    """Absolute paths of files tracked by git under ``path``."""
    root = repo_root(path)
    if root is None:
        return []
    out = _git(["ls-files", "-z", "--full-name", "--", "."], path)
    if not out:
        return []
    return [root / p for p in out.split("\0") if p]


def check_patch(root: Path, patch: str) -> str | None:
    """Dry-run ``git apply --check``; return an error message or None if it applies cleanly."""
    try:
        proc = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=root, input=patch, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return "git not installed"
    return proc.stderr.strip() or None if proc.returncode else None
