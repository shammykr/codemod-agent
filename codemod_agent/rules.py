"""Catalog of modernization rules. Each detector emits findings referencing a rule id."""

from __future__ import annotations

from dataclasses import dataclass

from codemod_agent.models import Finding, Severity

DEPRECATED_API = "deprecated-api"
OUTDATED_DEP = "outdated-dependency"
LEGACY = "legacy-pattern"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    category: str
    severity: Severity
    autofix: bool
    recommendation: str


_RULES = [
    # Python
    Rule(
        "PY001",
        "os.path usage",
        DEPRECATED_API,
        Severity.LOW,
        True,
        "Use pathlib.Path methods and the / operator instead of os.path functions.",
    ),
    Rule(
        "PY002",
        "old-style % string formatting",
        LEGACY,
        Severity.LOW,
        True,
        "Replace printf-style '%' formatting with an f-string.",
    ),
    Rule(
        "PY003",
        "deprecated unittest assertion alias",
        DEPRECATED_API,
        Severity.HIGH,
        True,
        "Use the canonical assertion name (aliases were removed in Python 3.12).",
    ),
    Rule(
        "PY004",
        "explicit 'object' base class",
        LEGACY,
        Severity.LOW,
        True,
        "Drop the redundant (object) base; all classes are new-style in Python 3.",
    ),
    Rule("PY005", "two-argument super()", LEGACY, Severity.LOW, True, "Use zero-argument super()."),
    Rule(
        "PY006",
        "__future__ import",
        LEGACY,
        Severity.LOW,
        True,
        "Remove Python 2 compatibility __future__ imports.",
    ),
    Rule(
        "PY007",
        "dict.has_key()",
        LEGACY,
        Severity.HIGH,
        True,
        "Use the 'in' operator; has_key() does not exist in Python 3.",
    ),
    Rule(
        "PY008",
        "Python 2 builtin",
        LEGACY,
        Severity.HIGH,
        True,
        "Replace Python 2 builtins (xrange, unicode, basestring, raw_input) with Python 3 ones.",
    ),
    Rule(
        "PY009",
        "deprecated or removed stdlib module",
        DEPRECATED_API,
        Severity.HIGH,
        False,
        "Migrate to the documented replacement module (manual change).",
    ),
    Rule(
        "PY010",
        "datetime.utcnow()",
        DEPRECATED_API,
        Severity.MEDIUM,
        True,
        "Use timezone-aware datetime.now(timezone.utc); utcnow() is deprecated in 3.12.",
    ),
    # JavaScript
    Rule(
        "JS001",
        "'var' declaration",
        LEGACY,
        Severity.LOW,
        True,
        "Use 'let' or 'const' for block-scoped declarations.",
    ),
    Rule(
        "JS002",
        "loose equality",
        LEGACY,
        Severity.LOW,
        True,
        "Use strict equality (=== / !==) to avoid implicit type coercion.",
    ),
    Rule(
        "JS003",
        "new Buffer()",
        DEPRECATED_API,
        Severity.HIGH,
        True,
        "Use Buffer.from() / Buffer.alloc(); the Buffer constructor is deprecated (DEP0005).",
    ),
    Rule(
        "JS004",
        "util.isArray()",
        DEPRECATED_API,
        Severity.MEDIUM,
        True,
        "Use Array.isArray(); util.isArray is deprecated (DEP0044).",
    ),
    Rule(
        "JS005",
        "deprecated Node.js API",
        DEPRECATED_API,
        Severity.MEDIUM,
        False,
        "Migrate to the supported API (manual change).",
    ),
    # Dependencies
    Rule(
        "DEP001",
        "outdated dependency",
        OUTDATED_DEP,
        Severity.MEDIUM,
        True,
        "Upgrade to the latest known version and run the test suite.",
    ),
    Rule(
        "DEP002",
        "deprecated package",
        OUTDATED_DEP,
        Severity.HIGH,
        False,
        "Replace the package with its maintained alternative (manual change).",
    ),
]

RULES: dict[str, Rule] = {r.id: r for r in _RULES}


def make_finding(
    rule_id: str,
    path: str,
    lines: list[str],
    line: int,
    end_line: int,
    target: str,
    message: str,
    severity: Severity | None = None,
    recommendation: str | None = None,
) -> Finding:
    rule = RULES[rule_id]
    return Finding(
        id="",
        rule=rule.id,
        title=rule.title,
        category=rule.category,
        severity=severity or rule.severity,
        file=path,
        line=line,
        end_line=end_line,
        snippet="".join(lines[line - 1 : end_line]),
        target=target,
        message=message,
        recommendation=recommendation or rule.recommendation,
        autofix=rule.autofix,
    )
