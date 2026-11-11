#!/usr/bin/env bash
# Runs the full pipeline on examples/legacy-project using the offline mock LLM.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
TARGET=examples/legacy-project
OUT=out
mkdir -p "$OUT"

if ! command -v codemod >/dev/null 2>&1; then
  echo "Installing codemod-agent (editable)..."
  "$PY" -m pip install -q -e .
fi

# The sample app's own smoke run is the "build/test" command checked after each change.
TEST_CMD="$PY main.py"
if command -v node >/dev/null 2>&1; then
  TEST_CMD="$TEST_CMD && node src/server.js"
fi

echo "== 1. Scan: dependency + API usage inventory"
codemod scan "$TARGET"

echo
echo "== 2. Plan: structured upgrade plan"
codemod plan "$TARGET" -o "$OUT/upgrade-plan.yaml"
sed -n '1,40p' "$OUT/upgrade-plan.yaml"

echo
echo "== 3. Generate: LLM changes, validated + verified one at a time"
codemod generate "$TARGET" -o "$OUT/changes.patch" --report "$OUT/report.json" --test-cmd "$TEST_CMD"

echo
echo "== 4. Patch preview"
sed -n '1,30p' "$OUT/changes.patch"
echo "..."
echo "Apply it with: git apply $OUT/changes.patch"
