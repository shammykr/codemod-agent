"""Walk a project and build the dependency + API usage inventory."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path

from codemod_agent import gitutils
from codemod_agent.analyzers import analyzer_for
from codemod_agent.analyzers.dependencies import MANIFESTS, parse_manifest
from codemod_agent.models import Inventory

log = logging.getLogger(__name__)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}


@dataclass
class Project:
    """A scanned project: where it lives and which files belong to it."""

    target: Path  # directory the user asked to analyze
    root: Path  # repo root if inside git, else target; diff paths are relative to this
    files: list[Path] = field(default_factory=list)
    git: dict[str, str] = field(default_factory=dict)

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def read(self, rel_path: str) -> str:
        return (self.root / rel_path).read_text(encoding="utf-8")


def _walk(target: Path) -> list[Path]:
    out = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(target).parts):
            out.append(p)
    return out


def discover(target: Path, tracked_only: bool = True, exclude: list[str] | None = None) -> Project:
    target = target.resolve()
    root = gitutils.repo_root(target)
    project = Project(target=target, root=root or target)
    files: list[Path] = []
    if root is not None:
        project.git = gitutils.repo_metadata(root)
        if tracked_only:
            files = [p for p in gitutils.tracked_files(target) if p.is_file()]
            if not files:
                log.warning("no tracked files under %s; falling back to directory walk", target)
    if not files:
        files = _walk(target)
    exclude = exclude or []
    project.files = [
        p
        for p in files
        if not SKIP_DIRS.intersection(p.parts)
        and not any(fnmatch.fnmatch(project.rel(p), pat) for pat in exclude)
    ]
    return project


def build_inventory(project: Project) -> Inventory:
    inv = Inventory(root=str(project.root), git=project.git)
    for path in project.files:
        rel = project.rel(path)
        if path.name in MANIFESTS:
            inv.dependencies.extend(parse_manifest(rel, path.read_text(encoding="utf-8")))
            continue
        analyzer = analyzer_for(rel)
        if analyzer is None:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        inv.files.append(analyzer.scan(rel, source))
    return inv
