# Codebase Modernization Agent

An AI-powered CLI that analyzes Python and JavaScript codebases for modernization
opportunities (deprecated APIs, outdated dependencies, legacy patterns) and generates
validated code changes as Git-ready diffs.

Static analysis finds the problems: the stdlib `ast` module for Python, pattern
scanning for JavaScript, and manifest parsing for dependencies. An LLM writes a
context-aware fix for each finding. Every fix is re-parsed. It is then applied on its
own and can be checked against your build/test command. If it fails, it is rolled
back. You get a structured upgrade plan and a patch you can run through `git apply`.

## Features

- **Scanning**: walks the project (only git-tracked files when inside a repo) and builds
  an inventory of imports, API calls and declared dependencies.
- **Detection**: 17 rules in three categories:
  - deprecated APIs: `os.path`, removed `unittest` aliases, `datetime.utcnow()`,
    `imp`/`distutils`/…, `new Buffer()`, `util.isArray()`, `url.parse()`
  - legacy patterns: `%` formatting, `class X(object)`, two-arg `super()`, `__future__`,
    `has_key`, `xrange`/`unicode`, `var`, loose equality
  - outdated or deprecated dependencies in `requirements.txt` / `package.json`, checked
    against a bundled known-versions list
- **Upgrade plan**: YAML/JSON output with steps ordered by severity. Each step lists the
  recommended change, the affected files and the finding ids.
- **LLM change generation**: one request per finding, including surrounding context. The
  default provider is an offline mock. Any OpenAI-compatible endpoint can be configured.
- **Structured validation**: each candidate file is re-parsed before a change is kept:
  `ast.parse` for Python, `node --check` for JS (with a bracket-balance check if Node
  isn't installed), and parsers for JSON and requirements files.
- **Build/test integration**: `--test-cmd "pytest -q"` runs your command after each
  change and reports pass/fail per change.
- **Rollback safety**: changes are applied one at a time. A change that fails
  validation or tests is reverted before the next one is tried. The working tree is
  restored at the end unless you pass `--write`.
- **Git-ready output**: produces a unified diff relative to the repo root and checks it
  with `git apply --check`.

## Architecture

```
            ┌────────────┐   git ls-files / rev-parse
  PATH ───▶ │  scanner   │◀──────────────────────────── gitutils
            └─────┬──────┘
                  │ files
       ┌──────────┼───────────────┐
       ▼          ▼               ▼
  PythonAnalyzer  JavaScriptAnalyzer  dependencies (+ known_versions.yaml)
   (ast)          (regex)             (requirements.txt, package.json)
       └──────────┼───────────────┘
                  ▼
         Inventory + Findings ─────────▶ plan.py ──▶ upgrade-plan.yaml / .json
                  │
                  ▼  for each automatable finding, in order
   ┌──────────────────────────────────────────────────────────────┐
   │ pipeline.py                                                  │
   │  re-anchor ─▶ LLM (mock | OpenAI-compatible) ─▶ apply in mem │
   │      ─▶ validate (AST / node --check / JSON) ─▶ write file   │
   │      ─▶ run --test-cmd ─▶ keep  or  roll back this change    │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
                 diffing.py ─▶ changes.patch ─▶ git apply --check
```

See [DESIGN.md](DESIGN.md) for the analysis pipeline and how to add a language.

## How to run

Requires Python 3.12+. Node.js is optional and enables `node --check` for JS validation.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

codemod scan     path/to/project                    # inventory
codemod plan     path/to/project -o plan.yaml       # upgrade plan (--format json too)
codemod generate path/to/project -o changes.patch \
    --test-cmd "pytest -q" --report report.json     # changes + verification
git apply changes.patch                             # run from the repo root
```

Useful flags: `--rule PY002 --rule JS001` (limit to these rules), `--min-severity medium`,
`--all-files` (also include untracked files), `--write` (keep the accepted changes in the
working tree), `--provider openai`.

### Demo

```bash
scripts/demo.sh
```

The demo runs scan → plan → generate on [`examples/legacy-project/`](examples/legacy-project),
a small inventory app with Python 2-era code, old JS, and outdated `requirements.txt` /
`package.json`. The app's own smoke run (`python main.py && node src/server.js`) is the
verification command.

### Using a real LLM

The mock provider runs offline. To use a real model, create `codemod.yaml` in the project
(see [`codemod.example.yaml`](codemod.example.yaml)) or pass `--config`:

```yaml
llm:
  provider: openai
  base_url: https://api.openai.com/v1   # or any OpenAI-compatible server (vLLM, Ollama, ...)
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
build:
  test_command: pytest -q
```

## Example output

`codemod generate examples/legacy-project --test-cmd "python3 main.py && node src/server.js"`

```
33 findings, 29 automatable; LLM provider: mock; verifying with: python3 main.py && node src/server.js
  F001 PY006  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F002 PY004  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F003 PY002  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F004 PY005  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F005 PY001  rejected-tests      examples/legacy-project/legacy_app/inventory.py  TypeError: unsupported operand type(s) for +: 'PosixPath' and 'str'
  F006 PY001  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F007 PY002  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  F008 PY010  applied             examples/legacy-project/legacy_app/inventory.py  tests passed
  ...
  F014 DEP001 applied             examples/legacy-project/package.json  tests passed
  ...
  F030 JS001  applied             examples/legacy-project/src/server.js  tests passed
  F031 JS001  rejected-validation examples/legacy-project/src/server.js  SyntaxError: Identifier 'label' has already been declared
  F032 JS002  applied             examples/legacy-project/src/server.js  tests passed
  F033 JS001  rejected-tests      examples/legacy-project/src/server.js  Error: describe() regression

Summary: applied=26, rejected-tests=2, rejected-validation=1
Patch with 26 changes written to out/changes.patch
git apply --check: OK
```

Three changes were dropped:

- **F005**: `os.path.join(...)` became `Path(...) / name`. That returns a `Path`, and a
  caller does `+ ".bak"`, so the smoke run failed and the change was rolled back.
- **F031**: `var` became `let` while the same name is redeclared with `var` later in the
  function. `node --check` rejected it.
- **F033**: the inner `var label` became a block-scoped `let`. It parsed, but it changed
  behaviour and the app's own check caught it.

Excerpt from the patch:

```diff
diff --git a/examples/legacy-project/legacy_app/inventory.py b/examples/legacy-project/legacy_app/inventory.py
--- a/examples/legacy-project/legacy_app/inventory.py
+++ b/examples/legacy-project/legacy_app/inventory.py
@@ -1,24 +1,25 @@
 # -*- coding: utf-8 -*-
 """Warehouse inventory helpers, originally written for Python 2.7."""
-from __future__ import print_function, unicode_literals

 import os
 from datetime import datetime
+from pathlib import Path
+from datetime import timezone
...
-class Item(object):
+class Item:
...
-        return "%s (%s) x%d" % (self.name, self.sku, self.qty)
+        return f"{self.name} ({self.sku}) x{self.qty}"
```

Excerpt from the upgrade plan (`codemod plan`, condensed):

```yaml
summary:
  files_scanned: 6
  languages: {python: 5, javascript: 1}
  dependencies: 8
  findings: 33
  by_severity: {low: 17, medium: 4, high: 12}
  by_category: {legacy-pattern: 16, deprecated-api: 9, outdated-dependency: 8}
  automatable: 29
steps:
- step: 1
  rule: DEP001
  title: outdated dependency
  severity: high
  recommended_change: Upgrade to the latest known version and run the test suite.
  automated: true
  affected_files: [examples/legacy-project/package.json, examples/legacy-project/requirements.txt]
  findings: [F014, F015, F017, F018, F019, F021]
```

## Project layout

```
codemod_agent/
  cli.py              Click entry point (scan / plan / generate)
  config.py           codemod.yaml loading
  models.py           Finding, Change, Inventory, ...
  rules.py            rule catalog (id, severity, category, autofix, recommendation)
  scanner.py          file discovery (git-aware), inventory, detection orchestration
  analyzers/          python.py (ast), javascript.py (regex), dependencies.py
  data/known_versions.yaml
  plan.py             upgrade plan builder
  llm/                base interface, prompts, mock, OpenAI-compatible provider
  changes.py          per-finding change generation and in-memory application
  validation.py       AST / node --check / JSON / requirements validation
  pipeline.py         apply → validate → test → keep or roll back
  diffing.py          git-style unified diffs
  gitutils.py         git subprocess helpers
examples/legacy-project/   sample outdated codebase
scripts/demo.sh            end-to-end demo
```

## License

MIT
