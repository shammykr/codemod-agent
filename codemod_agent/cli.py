"""Command-line interface: ``codemod scan | plan | generate``."""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from codemod_agent import __version__, gitutils
from codemod_agent.config import Config, load_config
from codemod_agent.llm import get_provider
from codemod_agent.models import ChangeResult, Finding, Inventory, Severity
from codemod_agent.pipeline import run
from codemod_agent.plan import build_plan, dump
from codemod_agent.scanner import Project, build_inventory, detect, discover

STATUS_COLORS = {
    "applied": "green",
    "rejected-validation": "red",
    "rejected-tests": "red",
    "conflict": "yellow",
    "no-change": "bright_black",
    "error": "red",
}


def common_options[F: Callable[..., Any]](func: F) -> F:
    options = [
        click.argument(
            "path", type=click.Path(exists=True, file_okay=False, path_type=Path), default="."
        ),
        click.option(
            "--config", "config_path", type=click.Path(exists=True, path_type=Path),
            help="Config file (default: <path>/codemod.yaml if present).",
        ),
        click.option(
            "--all-files", is_flag=True,
            help="Analyze every file, not only files tracked by git.",
        ),
        click.option(
            "--min-severity", type=click.Choice([s.value for s in Severity]),
            help="Ignore findings below this severity.",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _analyze(
    path: Path, config_path: Path | None, all_files: bool, min_severity: str | None
) -> tuple[Config, Project, Inventory, list[Finding]]:
    cfg = load_config(config_path, path)
    if all_files:
        cfg.analysis.tracked_only = False
    if min_severity:
        cfg.analysis.min_severity = Severity(min_severity)
    project = discover(path, cfg.analysis.tracked_only, cfg.analysis.exclude)
    inventory = build_inventory(project)
    findings = detect(
        project, inventory, set(cfg.analysis.disabled_rules), cfg.analysis.min_severity
    )
    return cfg, project, inventory, findings


def _write_or_echo(text: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        click.echo(f"wrote {output}", err=True)
    else:
        click.echo(text)


@click.group()
@click.version_option(__version__)
@click.option("-v", "--verbose", is_flag=True)
def main(verbose: bool) -> None:
    """Analyze a codebase for modernization opportunities and generate validated changes."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s: %(message)s"
    )


@main.command()
@common_options
@click.option("--format", "fmt", type=click.Choice(["text", "json", "yaml"]), default="text")
@click.option("-o", "--output", type=click.Path(path_type=Path))
def scan(
    path: Path, config_path: Path | None, all_files: bool, min_severity: str | None,
    fmt: str, output: Path | None,
) -> None:
    """Build the dependency and API-usage inventory of PATH."""
    _, project, inventory, _ = _analyze(path, config_path, all_files, min_severity)
    if fmt != "text":
        _write_or_echo(dump(inventory.to_dict(), fmt), output)
        return
    langs = Counter(f.language for f in inventory.files)
    git = project.git
    click.secho(f"Project: {project.target}", bold=True)
    if git:
        click.echo(f"Git:     {git.get('branch', '?')} @ {git.get('head', '?')} (tracked files)")
    click.echo(f"Files:   {', '.join(f'{n} {lang}' for lang, n in langs.items()) or 'none'}")
    click.secho("\nDependencies", bold=True)
    for d in inventory.dependencies:
        click.echo(f"  {d.ecosystem:5} {d.name:20} {d.version:10} {d.manifest}")
    imports: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    for f in inventory.files:
        imports.update(f.imports)
        calls.update(f.api_calls)
    click.secho("\nImports (by file count)", bold=True)
    for name, n in imports.most_common(10):
        click.echo(f"  {n:3}  {name}")
    click.secho("\nAPI usage (top calls)", bold=True)
    for name, n in calls.most_common(10):
        click.echo(f"  {n:3}  {name}")


@main.command()
@common_options
@click.option("--format", "fmt", type=click.Choice(["yaml", "json"]), default="yaml")
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Write plan to a file.")
def plan(
    path: Path, config_path: Path | None, all_files: bool, min_severity: str | None,
    fmt: str, output: Path | None,
) -> None:
    """Detect modernization opportunities and emit a structured upgrade plan."""
    _, _, inventory, findings = _analyze(path, config_path, all_files, min_severity)
    _write_or_echo(dump(build_plan(inventory, findings), fmt), output)


@main.command()
@common_options
@click.option("-o", "--output", type=click.Path(path_type=Path), default=Path("codemod.patch"),
              show_default=True, help="Where to write the unified diff.")
@click.option("--report", type=click.Path(path_type=Path), help="Write a JSON per-change report.")
@click.option("--test-cmd", help="Build/test command to run after each change (e.g. 'pytest').")
@click.option("--provider", type=click.Choice(["mock", "openai"]), help="Override llm.provider.")
@click.option("--rule", "rules", multiple=True, help="Only generate changes for these rule ids.")
@click.option("--write", is_flag=True, help="Leave accepted changes applied to the working tree.")
def generate(
    path: Path, config_path: Path | None, all_files: bool, min_severity: str | None,
    output: Path, report: Path | None, test_cmd: str | None, provider: str | None,
    rules: tuple[str, ...], write: bool,
) -> None:
    """Generate, validate and verify changes; output them as a git-applicable patch."""
    cfg, project, _, findings = _analyze(path, config_path, all_files, min_severity)
    if provider:
        cfg.llm.provider = provider
    test_cmd = test_cmd or cfg.build.test_command
    if rules:
        findings = [f for f in findings if f.rule in rules]
    try:
        llm = get_provider(cfg.llm)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    todo = [f for f in findings if f.autofix]
    click.secho(
        f"{len(findings)} findings, {len(todo)} automatable; LLM provider: {llm.name}"
        + (f"; verifying with: {test_cmd}" if test_cmd else ""),
        bold=True,
    )

    def show(r: ChangeResult) -> None:
        status = click.style(f"{r.status:19}", fg=STATUS_COLORS.get(r.status))
        click.echo(f"  {r.finding_id} {r.rule:6} {status} {r.file}  {r.detail}")

    try:
        result = run(project, findings, llm, test_cmd, cfg.build.timeout, write, show)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    counts = Counter(r.status for r in result.results)
    click.secho("\nSummary: " + ", ".join(f"{k}={v}" for k, v in counts.items()), bold=True)
    if not result.patch:
        click.echo("No changes accepted; nothing to write.")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.patch)
    click.echo(f"Patch with {len(result.applied)} changes written to {output}")
    if write:
        click.echo("Changes were also applied to the working tree (--write).")
    elif project.git:
        error = gitutils.check_patch(project.root, result.patch)
        click.echo(
            f"git apply --check: {'OK' if error is None else 'FAILED: ' + error}\n"
            f"Apply from {project.root} with: git apply {output.resolve()}"
        )
    if report:
        report.write_text(json.dumps([r.__dict__ for r in result.results], indent=2))
        click.echo(f"Report written to {report}")
