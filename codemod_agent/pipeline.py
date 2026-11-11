"""Apply changes one at a time with validation, build/test verification and rollback."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from codemod_agent.changes import apply_change, generate_change
from codemod_agent.diffing import combine, unified_diff
from codemod_agent.llm import LLMProvider
from codemod_agent.models import ChangeResult, Finding
from codemod_agent.scanner import Project
from codemod_agent.validation import validate

log = logging.getLogger(__name__)


@dataclass
class CommandResult:
    ok: bool
    output: str


@dataclass
class RunReport:
    results: list[ChangeResult] = field(default_factory=list)
    patch: str = ""
    baseline: CommandResult | None = None

    @property
    def applied(self) -> list[ChangeResult]:
        return [r for r in self.results if r.status == "applied"]


def run_command(cmd: str, cwd: Path, timeout: float) -> CommandResult:
    """Run the user's build/test command through the shell."""
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, f"timed out after {timeout:.0f}s")
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-5:])
    return CommandResult(proc.returncode == 0, tail)


class Workspace:
    """Tracks original and current content of touched files; restores on demand."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.original: dict[str, str] = {}
        self.current: dict[str, str] = {}

    def get(self, rel: str) -> str:
        if rel not in self.current:
            self.original[rel] = self.current[rel] = self.project.read(rel)
        return self.current[rel]

    def write_disk(self, rel: str, content: str) -> None:
        (self.project.root / rel).write_text(content, encoding="utf-8")

    def restore_all(self) -> None:
        for rel, content in self.original.items():
            self.write_disk(rel, content)

    def flush(self) -> None:
        for rel, content in self.current.items():
            self.write_disk(rel, content)

    def patch(self) -> str:
        rels = sorted(self.current)
        return combine([unified_diff(r, self.original[r], self.current[r]) for r in rels])


def run(
    project: Project,
    findings: list[Finding],
    provider: LLMProvider,
    test_command: str | None = None,
    timeout: float = 600.0,
    write: bool = False,
    on_result: Callable[[ChangeResult], None] | None = None,
) -> RunReport:
    """Generate, validate and (optionally) test each change individually.

    A change is kept only if the file still re-parses and, when ``test_command`` is
    given, the command still passes with the change on disk. Otherwise that single
    change is reverted and the next one is attempted, so partial upgrades are safe.
    Unless ``write`` is set, the working tree is restored at the end and the accepted
    changes exist only as a patch.
    """
    report = RunReport()
    ws = Workspace(project)
    if test_command:
        report.baseline = run_command(test_command, project.target, timeout)
        if not report.baseline.ok:
            raise RuntimeError(
                "build/test command fails before any change; fix it or omit --test-cmd:\n"
                + report.baseline.output
            )

    def record(result: ChangeResult) -> None:
        report.results.append(result)
        if on_result:
            on_result(result)

    try:
        for finding in findings:
            if not finding.autofix:
                continue
            base = ws.get(finding.file)
            result = ChangeResult(finding.id, finding.rule, finding.file, "no-change")
            try:
                change = generate_change(provider, finding, base)
            except Exception as exc:  # provider/network errors shouldn't abort the run
                result.status, result.detail = "error", f"LLM call failed: {exc}"
                record(result)
                continue
            if change is None:
                result.detail = "model returned no safe change"
                record(result)
                continue
            updated = apply_change(base, change)
            if updated is None:
                result.status = "conflict"
                result.detail = "original lines changed by an earlier edit"
                record(result)
                continue
            error = validate(finding.file, updated)
            if error:
                result.status, result.detail = "rejected-validation", error
                record(result)
                continue
            if test_command:
                ws.write_disk(finding.file, updated)
                outcome = run_command(test_command, project.target, timeout)
                if not outcome.ok:
                    ws.write_disk(finding.file, base)  # roll back this change only
                    result.status = "rejected-tests"
                    result.detail = outcome.output.splitlines()[-1] if outcome.output else ""
                    record(result)
                    continue
            ws.current[finding.file] = updated
            result.status = "applied"
            result.detail = "tests passed" if test_command else "validated"
            result.diff = unified_diff(finding.file, base, updated)
            record(result)
    finally:
        if write:
            ws.flush()
        else:
            ws.restore_all()
    report.patch = ws.patch()
    return report
