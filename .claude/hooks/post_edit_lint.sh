#!/usr/bin/env bash
# PostToolUse hook: cheap lint pass after Edit / Write.
#
# Reads tool_input.file_path from the JSON stdin payload. Python files get
# 'ruff check' (findings to stderr, non-blocking). Other file types are a
# no-op with a note. Design choice: never exit non-zero. Lint findings
# surface as hints, not enforcement. Real enforcement belongs in CI.

set -u

file_path=$(python -c "import json,sys; d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('file_path','') or '')" 2>/dev/null)
[[ -z "$file_path" || ! -f "$file_path" ]] && exit 0

case "$file_path" in
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff check "$file_path" >&2 || true
    else
      echo "[post_edit_lint] ruff not on PATH; skip Python lint." >&2
    fi
    ;;
  *)
    echo "[post_edit_lint] no linter for ${file_path##*/}; skipping." >&2
    ;;
esac
