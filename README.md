# claude-config

A cleaned-up snapshot of my daily Claude Code setup: the skills, sub-agents, hooks, and MCP servers I actually work with, sanitized for public sharing.

Everything here runs against the synthetic data in `examples/`. Nothing is aspirational scaffolding.

## Components

| Component | Type | What it does | Why I built it |
|---|---|---|---|
| `daily-briefing` | skill | Turns exported email/calendar data into a self-contained HTML briefing with overview stats, today/tomorrow calendar, open action items, and carry-over to-dos. | Replaces the five minutes I used to spend every morning stitching context together by hand. |
| `pdf-clause-extract` | skill | Rasterizes a scanned PDF with `pdftoppm`, sends pages to the Claude API against a small clause schema, and writes validated JSON + CSV. | Direct text extraction fails on scanned or bad-font PDFs; rasterize-then-VLM is the workflow that actually held up. |
| `codebase-mapper` | sub-agent | Explores an unfamiliar repo (read-only) and returns a compact mental model: entry points, module responsibilities, data flow, and the three files a new contributor should read first. | Verbose exploration stays in the sub-agent's context; only the distilled map returns to the main thread. |
| `pipeline-reviewer` | sub-agent | Reviews PySpark / Databricks pipeline code against a concrete checklist: schema drift, partition and shuffle red flags, medallion-layer hygiene, MLflow logging completeness, cost traps. | Turns "vibes-based" pipeline review into a repeatable checklist. |
| `guard_dangerous_commands.py` | hook | PreToolUse hook on Bash. Blocks `rm -rf` outside the project, force pushes, writes to `.env`, and unbounded `DROP` / `DELETE` in SQL strings. | Deterministic safety over prompt-level suggestions. Applies my persistent-agent capability-tier design to Claude Code. |
| `post_edit_lint.sh` | hook | PostToolUse hook on Edit/Write. Runs `ruff` on edited Python; no-op with a note otherwise. | Cheap continuous feedback loop on file writes. |
| `mlflow-lookup` | MCP server | Two tools: `list_runs(experiment_name, max_results)` and `get_run(run_id)`. Targets a local MLflow tracking URI so no cloud account is needed. | Query experiment state from inside Claude Code instead of switching to the MLflow UI. |

Each component gets a "why" section further down once its phase lands.

## Design principles

- **Deterministic first.** Scripts and hooks for anything that must happen every time; LLM judgment reserved for the parts that actually need judgment.
- **Permission tiers on tools.** Read-only sub-agents stay read-only; the guard hook blocks the destructive patterns unconditionally.
- **Evaluation before trust.** Prompts live in versioned files so I can iterate and compare, not inline strings that quietly drift.

## Setup

Prerequisites: Python 3.11+, `pdftoppm` (from Poppler) for `pdf-clause-extract`, `ruff` for the post-edit hook, `uv` or `pip` for the MCP server.

1. Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`.
2. See each component's section for its specific trigger.

Full component-by-component setup lands with the final README pass.

## Status

Work-in-progress. Building this in phases; commits land per meaningful unit rather than per phase.
