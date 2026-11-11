"""Parse dependency manifests and compare against bundled known versions."""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any

import yaml

from codemod_agent.models import Dependency, Finding, Severity
from codemod_agent.rules import make_finding

REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|>=|~=|<=|>|<)?\s*([0-9][\w.]*)?")
MANIFESTS = ("requirements.txt", "package.json")


def parse_requirements(path: str, text: str) -> list[Dependency]:
    deps = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = REQ_RE.match(line)
        if m and m.group(3):
            deps.append(Dependency(m.group(1).lower(), m.group(3), "pypi", path, i))
    return deps


def parse_package_json(path: str, text: str) -> list[Dependency]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    lines = text.splitlines()
    deps = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            version = re.sub(r"^[\^~>=<\s]+", "", str(spec))
            if not re.match(r"\d", version):
                continue
            pattern = re.compile(rf'"{re.escape(name)}"\s*:')
            line = next((i for i, ln in enumerate(lines, 1) if pattern.search(ln)), 0)
            deps.append(Dependency(name, version, "npm", path, line))
    return deps


def parse_manifest(path: str, text: str) -> list[Dependency]:
    if path.endswith("package.json"):
        return parse_package_json(path, text)
    return parse_requirements(path, text)


@cache
def known_versions() -> dict[str, dict[str, Any]]:
    text = resources.files("codemod_agent").joinpath("data/known_versions.yaml").read_text()
    data: dict[str, dict[str, Any]] = yaml.safe_load(text)
    return data


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3])


def check_dependencies(deps: list[Dependency], sources: dict[str, str]) -> list[Finding]:
    """Flag outdated (DEP001) and deprecated (DEP002) dependencies."""
    known = known_versions()
    findings = []
    for dep in deps:
        entry = known.get(dep.ecosystem, {}).get(dep.name)
        if entry is None or dep.line == 0:
            continue
        lines = sources[dep.manifest].splitlines(keepends=True)
        if isinstance(entry, dict) and entry.get("deprecated"):
            findings.append(
                make_finding(
                    "DEP002", dep.manifest, lines, dep.line, dep.line, dep.name,
                    f"{dep.name} {dep.version} is deprecated/unmaintained.",
                    recommendation=f"Replace {dep.name} with {entry['deprecated']}.",
                )
            )
            continue
        latest = str(entry["latest"] if isinstance(entry, dict) else entry)
        cur, new = version_tuple(dep.version), version_tuple(latest)
        if cur >= new:
            continue
        if cur[:1] < new[:1]:
            severity = Severity.HIGH
        elif cur[:2] < new[:2]:
            severity = Severity.MEDIUM
        else:
            severity = Severity.LOW
        findings.append(
            make_finding(
                "DEP001", dep.manifest, lines, dep.line, dep.line, dep.version,
                f"{dep.name} {dep.version} is behind the latest known version {latest}.",
                severity=severity,
                recommendation=f"Upgrade {dep.name} to {latest}.",
            )
        )
    return findings
