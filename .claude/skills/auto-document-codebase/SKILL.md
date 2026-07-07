---
name: auto-document-codebase
description: "Regenerates CODEBASE_DOCS.md from workspace source files (.py, .ipynb, .sql, .yml, .yaml). Emits descriptions (docstrings, leading comments, YAML name+description pairs) with file:line citations, a Mermaid dependency diagram, TODO/FIXME index, and a diff since last regen. Never inlines source. Use when a repo needs a compact, always-fresh map of what each file does."
---

# auto-document-codebase

Generates a single Markdown document that maps a codebase by description, not by source. Runs deterministically over a scan set, produces the same output every time given the same input, and highlights what changed since the previous run via a sidecar snapshot.

## What it produces

`CODEBASE_DOCS.md` at the repo root (configurable), organized as:

1. Header with UTC timestamp and a "do not edit by hand" note
2. Coverage summary (file count, class count, function count, SQL def count, undocumented count, TODO count)
3. Changes since last regen (added / removed files, added / removed classes / functions / SQL defs)
4. Mermaid `flowchart LR` dependency diagram
5. Dependency-ordered file index (topo sort of Python imports and notebook `%run` targets)
6. Undocumented callables list, with `file:line` citations, so gaps are visible
7. TODO / FIXME / HACK / XXX index
8. Per-file sections in dependency order, each with:
   - Module docstring, SQL leading comment, or YAML `name` + `description` pairs
   - Each class: signature, bases, `file:line`, docstring or "no class docstring", method list with one-line summaries
   - Each function: signature, `file:line`, full docstring or "no docstring"
   - SQL: every `CREATE TABLE / VIEW / FUNCTION / PROCEDURE` (including `MATERIALIZED VIEW`) with `file:line`

The doc never inlines source code. Missing docstrings are flagged so you can backfill them in the source itself, then rerun.

## When to invoke

- The user asks to "update docs" / "regen docs" / "document the codebase".
- After adding, moving, or refactoring a workspace file, if you want the map to stay current.
- As a `PostToolUse` hook after `Write` / `Edit` / `MultiEdit` / `NotebookEdit` for zero-friction auto-refresh (see below).

## Usage

Default scan: the `src/` directory relative to the current working directory.

```
python .claude/skills/auto-document-codebase/generate_docs.py
```

Custom scan set:

```
python .claude/skills/auto-document-codebase/generate_docs.py \
  --scan .claude/hooks .claude/skills mcp-servers
```

Or via env var (comma-separated):

```
AUTODOC_SCAN_DIRS=.claude/hooks,.claude/skills python .claude/skills/auto-document-codebase/generate_docs.py
```

Other flags:

- `--output PATH` (default `CODEBASE_DOCS.md`)
- `--state PATH` (default `.claude/skills/auto-document-codebase/.state.json`; used for the diff-since-last-regen)
- `--root PATH` (default `.`; used to normalize module names for the Python dep graph)

Stdlib only. `PyYAML` is optional: with it, YAML files are fully parsed for `name` + `description` at any nesting depth; without it, YAML parsing falls back to top-level-key extraction via regex.

## Optional PostToolUse hook

To auto-refresh on any file save, add this hook block to `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/skills/auto-document-codebase/generate_docs.py\""
          }
        ]
      }
    ]
  }
}
```

The script is fast (stdlib-only, self-filtering by scan set) and idempotent, so out-of-scope edits produce a no-op regen.

## What it skips

`EXCLUDE_DIRS` (see `generate_docs.py`): `.git`, `.venv`, `venv`, `env`, `__pycache__`, `.ipynb_checkpoints`, `node_modules`, `dist`, `build`, `.claude`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, plus `.hg`, `.svn`.

`EXCLUDE_NAMES`: `CODEBASE_DOCS.md`, `README.md`.

Edit `generate_docs.py` if you need a different set. The exclusion is by path part, so a nested `.claude` is caught anywhere it appears.

## Edge cases

- **Syntax-broken files**: captured as `⚠️ Parse error: ...` in the per-file section; the rest of the run continues.
- **Cyclic Python imports**: topo sort emits the acyclic subgraph first, then the leftover cycle members in alphabetical order.
- **Empty scan**: the doc is written as a placeholder ("Nothing found under X") and the state file is reset so the next run treats every discovered file as an addition.
- **Notebook `%run`**: `# MAGIC %run ./foo` and `%run /Workspace/path/foo` count as dependencies. Matching is by filename.
- **Sidecar `.state.json`**: safe to delete; the next run just treats everything as an addition. Don't hand-edit.

## Follow-up

After a regen, offer to fix the top items in the "Undocumented callables" section by adding docstrings to the source. That's the correct place for descriptions; the generated doc is a build artifact and gets overwritten.
