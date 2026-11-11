"""Turn findings into a structured, ordered upgrade plan (YAML or JSON)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import yaml

from codemod_agent.models import Finding, Inventory
from codemod_agent.rules import RULES
from codemod_agent.scanner import SEVERITY_ORDER


def build_plan(inventory: Inventory, findings: list[Finding]) -> dict[str, Any]:
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    steps = []
    ordered = sorted(
        by_rule.items(),
        key=lambda kv: (min(SEVERITY_ORDER[f.severity] for f in kv[1]), kv[0]),
    )
    for order, (rule_id, group) in enumerate(ordered, start=1):
        rule = RULES[rule_id]
        worst = min((f.severity for f in group), key=lambda s: SEVERITY_ORDER[s])
        steps.append(
            {
                "step": order,
                "rule": rule_id,
                "title": rule.title,
                "category": rule.category,
                "severity": str(worst),
                "recommended_change": rule.recommendation,
                "automated": rule.autofix,
                "affected_files": sorted({f.file for f in group}),
                "findings": [f.id for f in group],
            }
        )

    languages = Counter(fi.language for fi in inventory.files)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "project": inventory.root,
        "git": inventory.git,
        "summary": {
            "files_scanned": len(inventory.files),
            "languages": dict(languages),
            "dependencies": len(inventory.dependencies),
            "findings": len(findings),
            "by_severity": dict(Counter(str(f.severity) for f in findings)),
            "by_category": dict(Counter(f.category for f in findings)),
            "automatable": sum(f.autofix for f in findings),
        },
        "steps": steps,
        "findings": [
            {
                "id": f.id,
                "rule": f.rule,
                "severity": str(f.severity),
                "file": f.file,
                "line": f.line,
                "message": f.message,
                "recommended_change": f.recommendation,
                "code": f.snippet.rstrip("\n"),
            }
            for f in findings
        ],
    }


def dump(data: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
