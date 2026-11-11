"""Parse dependency manifests (requirements.txt, package.json)."""

from __future__ import annotations

import json
import re

from codemod_agent.models import Dependency

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
