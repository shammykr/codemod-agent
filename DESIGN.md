# Design

## Goals

1. Find modernization opportunities with **deterministic static analysis**. The LLM never
   decides *what* to change, only *how* to rewrite a specific, already-located snippet.
2. Treat every LLM output as untrusted. A change is kept only if it re-parses and, when
   configured, the project's own build/test command still passes.
3. Never leave the repository half-upgraded. Changes are atomic per finding, and the
   default output is a patch, not an edited working tree.

## Architecture

```
scanner ──▶ analyzers ──▶ findings ──▶ plan
                              │
                              ▼
                   pipeline (per finding)
        re-anchor → LLM → apply → validate → test → keep | revert
                              │
                              ▼
                     diffing → patch → git apply --check
```

| Module | Responsibility |
|---|---|
| `scanner.py` | Discover files (git-tracked when in a repo), build the `Inventory`, run detectors, assign finding ids |
| `analyzers/` | One `LanguageAnalyzer` per language (`scan` + `detect`), plus manifest parsing |
| `rules.py` | Rule catalog: id, title, category, severity, `autofix`, recommendation |
| `plan.py` | Group findings by rule into ordered steps; YAML/JSON output |
| `llm/` | `LLMProvider` interface, prompt template + response parser, mock and OpenAI-compatible providers |
| `changes.py` | Build the per-finding request (snippet + context) and apply a `Change` in memory |
| `validation.py` | Per-file-type syntax validation |
| `pipeline.py` | Sequential apply / validate / test / rollback loop |
| `diffing.py`, `gitutils.py` | Unified diffs; git metadata, tracked files, `git apply --check` |

## Analysis pipeline

### 1. Discovery

`discover()` resolves the git root with `git rev-parse --show-toplevel` and lists files
with `git ls-files --full-name`, so build output, vendored code and other untracked files
are skipped. The repo's branch, HEAD and remote are recorded in the plan. Every path in
the pipeline is relative to the **repo root**, which keeps the patch applicable with
`git apply` from there. Outside a repo, or with `--all-files`, the tool walks the
directory instead and skips `node_modules`, virtualenvs and similar directories.

### 2. Inventory

Each source file goes to the analyzer registered for its extension:

- **Python**: `ast.parse`. Imports are recorded, and calls are resolved through import
  aliases (`from os import path as p; p.join()` → `os.path.join`) to count API usage.
- **JavaScript**: comments are stripped with line numbers preserved, then regexes collect
  `require()`/`import` sources and member calls. A full JS parser is out of scope; the
  rules only need line-level patterns.
- **Manifests**: `requirements.txt` and `package.json` (`dependencies` and
  `devDependencies`), with the line number of each entry so it can be patched.

### 3. Detection

Detectors emit `Finding`s carrying the rule id, the exact source lines (`snippet`), the
matched expression (`target`), a severity and a recommendation.

- Python rules are an `ast.NodeVisitor`, so matches are structural. A `%` formatting
  finding is a `BinOp(Mod)` with a string-literal left operand, not a regex hit inside a
  string.
- JS rules run on a version of the line with comments removed and string literals
  blanked, so `"a == b"` inside a string is not flagged. `x == null` is exempt because it
  is the idiomatic null-or-undefined check.
- Dependency rules compare versions against `data/known_versions.yaml`. A major-version
  gap is high severity, minor is medium and patch is low. Deprecated packages (`request`,
  `six`, `nose`, …) get a manual replacement recommendation.

Each rule has an `autofix` flag. Rules where a correct rewrite needs a migration
(`imp` → `importlib`, deprecated packages) appear in the plan, but no change is
generated for them.

### 4. Plan

Findings are grouped by rule into steps, ordered by worst severity. Each step lists the
recommended change, whether it is automated, the affected files and the finding ids. The
plan also contains per-finding details and summary counts, so it doubles as a report.

### 5. Change generation and verification

`pipeline.run()` processes automatable findings in file/line order:

1. **Re-anchor.** Earlier accepted edits may have shifted lines or rewritten part of the
   same line. The pipeline tracks the net line delta per file. A finding is mapped to its
   shifted location, and if its exact lines are gone but the matched expression is still
   there, the snippet is refreshed from the current content. Otherwise the result is
   `conflict`.
2. **LLM request.** The prompt holds the rule, the recommendation, the matched
   expression, the lines to rewrite and ±8 lines of context taken from the *current*
   file, so the model sees earlier fixes. The model replies with JSON:
   `{"replacement", "imports", "explanation"}`. Returning `null` means "no safe change".
3. **Apply in memory.** The original lines are located (nearest match to the expected
   line) and replaced. Required imports are inserted after the last top-level import if
   they are missing.
4. **Validate.** `.py` → `ast.parse`; `.js` → `node --check` (falling back to a
   delimiter-balance check without Node); `.json` → `json.loads`;
   `requirements*.txt` → requirement grammar. A failure gives `rejected-validation`, and
   since the file on disk was never touched there is nothing to revert.
5. **Test.** If a test command is set, the file is written and the command runs in the
   project directory. A non-zero exit restores the file to its pre-change content
   (`rejected-tests`). A baseline run happens first, and the run aborts if the project
   is already failing, because otherwise no change could be judged.
6. **Keep.** The new content becomes the base for later findings, and the per-change
   diff is recorded.

A `try/finally` restores every touched file to its original content at the end, even on
Ctrl-C. With `--write`, the accepted state is written instead. The combined patch is
`original → final` for each file and is verified with `git apply --check`.

### Why one change at a time

Applying all changes and then testing cannot tell you *which* change broke the build,
and one bad change would block every good one. Testing per change costs one test run
per finding. That is the price of attributing every failure and keeping partial
upgrades safe. Use `--rule` or `--min-severity` to scope large runs.

## LLM providers

`LLMProvider.suggest(ChangeRequest) -> Suggestion | None` is the only contract.

- `MockProvider` gives deterministic, rule-specific rewrites, so the tool runs offline
  and in CI. Its output goes through the same JSON parser as real model output. Some of
  its rewrites are deliberately imperfect, as a model's would be (`os.path.join` →
  `Path / x` changes the return type). This exercises the validation and rollback paths.
- `OpenAICompatibleProvider` POSTs to `{base_url}/chat/completions` using only the
  standard library. It works with OpenAI, Azure-style gateways, vLLM, Ollama and other
  OpenAI-compatible servers. The API key is read from the env var named in the config.
  Provider errors are reported per finding (`error`) and don't abort the run.

## Extensibility: adding a language analyzer

1. Create `codemod_agent/analyzers/<lang>.py` with a `LanguageAnalyzer` subclass:

   ```python
   class GoAnalyzer(LanguageAnalyzer):
       language = "go"
       extensions = (".go",)

       def scan(self, path: str, source: str) -> FileInventory: ...
       def detect(self, path: str, source: str) -> list[Finding]: ...
   ```

   `detect` builds findings with `rules.make_finding(rule_id, path, lines, line,
   end_line, target, message)`. The snippet must be whole source lines, because
   replacements are line-based.
2. Register an instance in `analyzers/__init__.py::ANALYZERS`.
3. Add the rules to `rules.py` (ids prefixed by language, e.g. `GO001`) with severity,
   category, `autofix` and recommendation.
4. Add a validator branch in `validation.py` (e.g. `gofmt -e`) so generated changes are
   re-parsed before inclusion.
5. Optionally add rewrites for the new rules to `llm/mock.py::REWRITES` so the offline
   demo covers them. Real providers need no changes because the prompt is
   language-agnostic.

New dependency ecosystems need a parser in `analyzers/dependencies.py`, a section in
`known_versions.yaml` and an entry in `MANIFESTS`.

## Non-goals and limitations

- JS analysis is pattern-based. It works on single lines and ignores scope, which is why
  validation and test runs back it up.
- `known_versions.yaml` is a bundled snapshot, not a live registry query, so results are
  reproducible and work offline.
- Multi-file refactors (renaming a function across modules) are out of scope. Each change
  is local to one finding.
