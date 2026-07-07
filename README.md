# claude-config

A cleaned-up snapshot of my daily Claude Code setup: the skills, sub-agents, hooks, and MCP servers I actually work with, sanitized for public sharing.

Everything here runs against the synthetic data in `examples/`. Nothing is aspirational scaffolding.

## Components

| Component | Type | What it does | Why I built it |
|---|---|---|---|
| `daily-briefing` | skill | Turns exported email/calendar data into a self-contained HTML briefing with overview stats, today/tomorrow calendar, open action items, and carry-over to-dos. | Replaces the five minutes I used to spend every morning stitching context together by hand. |
| `pdf-clause-extract` | skill | Rasterizes a scanned PDF with `pdftoppm`, sends pages to the Claude API against a small clause schema, and writes validated JSON + CSV. | Direct text extraction fails on scanned or bad-font PDFs; rasterize-then-VLM is the workflow that actually held up. |
| `auto-document-codebase` | skill | Regenerates `CODEBASE_DOCS.md` from workspace files (`.py`, `.ipynb`, `.sql`, `.yml`, `.yaml`). Emits descriptions only, with `file:line` citations, a Mermaid dep diagram, TODO index, and a diff-since-last-regen. Idempotent. | An always-current file-level map of the codebase, driven from the source itself, without hand-maintained docs going stale. |
| `databricks-submit-poll` | skill | Submits a one-off Databricks run via `POST /api/2.1/jobs/runs/submit`, polls `runs/get` until terminal, prints state transitions and the run URL. Stdlib-only Python; no SDK. | Ad-hoc job execution without spinning up a permanent Databricks Job for something you'll run once. |
| `codebase-mapper` | sub-agent | Explores an unfamiliar repo (read-only) and returns a compact mental model: entry points, module responsibilities, data flow, and the three files a new contributor should read first. | Verbose exploration stays in the sub-agent's context; only the distilled map returns to the main thread. |
| `pipeline-reviewer` | sub-agent | Reviews PySpark / Databricks pipeline code against a concrete checklist: schema drift, partition and shuffle red flags, medallion-layer hygiene, MLflow logging completeness, cost traps. | Turns "vibes-based" pipeline review into a repeatable checklist. |
| `databricks-table-eda` | sub-agent | Given a `catalog.schema.table`, returns schema, row count, sample rows, per-column null rates, and partition info. Prefers Databricks MCP tools if configured; falls back to raw SQL through any Databricks execute path. Read-only. | Fastest way to know whether a UC table is worth using before writing code against it. |
| `guard_dangerous_commands.py` | hook | PreToolUse hook on Bash. Blocks `rm -rf` outside the project, force pushes, writes to `.env`, and unbounded `DROP` / `DELETE` in SQL strings. | Deterministic safety over prompt-level suggestions. Applies my persistent-agent capability-tier design to Claude Code. |
| `post_edit_lint.sh` | hook | PostToolUse hook on Edit/Write/MultiEdit. Runs `ruff` on edited Python; no-op with a note otherwise. | Cheap continuous feedback loop on file writes. |
| `warn_unpinned_deps.py` | hook | PostToolUse hook. Scans edited `pyproject.toml` / `requirements.txt` / `requirements-*.txt` and warns on unpinned entries. Never blocks. | Surfaces version drift at save time. Long-running automated jobs are the usual victims of an unpinned `>=1.5` that silently bumps overnight. |
| `mlflow-lookup` | MCP server | Two tools: `list_runs(experiment_name, max_results)` and `get_run(run_id)`. Targets a local MLflow tracking URI so no cloud account is needed. | Query experiment state from inside Claude Code instead of switching to the MLflow UI. |

## Design principles

- **Deterministic first.** Scripts and hooks for anything that must happen every time. LLM judgment stays where judgment is genuinely needed.
- **Permission tiers on tools.** Read-only sub-agents stay read-only via `tools: Read, Grep, Glob` in frontmatter. The Bash guard hook blocks the destructive patterns unconditionally.
- **Evaluation before trust.** Prompts live in versioned files, not inline strings, so they can be diffed and iterated on.

## Why each piece exists

### `daily-briefing`

Every morning I was spending five minutes stitching yesterday's leftovers into today's context. The skill takes JSON exports of email + calendar and produces one self-contained HTML file with overview stats, today/tomorrow calendar, open action items, and things that got done since yesterday. Notable design choices: no LLM anywhere in the pipeline (keyword matching plus regex due-date parsing plus timestamp comparisons, so it's deterministic and reproducible), a **negation guard** so "no action needed" isn't parroted back as a to-do, and a JSON `.state.json` sidecar for carry-forward rather than scraping the previous HTML. Runnable end-to-end against `examples/sample_briefing_data/` via one command in the skill's `SKILL.md`.

### `pdf-clause-extract`

For contracts and other PDFs where copy-paste produces gibberish, whether because the file is a scan or because the fonts use custom glyph encodings. Rasterize each page with `pdftoppm`, send the PNG to the Claude API against a four-field schema (`party`, `clause_type`, `responsibility`, `page`), validate the JSON, write a CSV. The prompt lives in its own file (`prompts/extraction_prompt.md`) so it has an independent change history; the driver overwrites the `page` field returned by the model because the model drifts on that and the caller doesn't. A synthetic 2-page lease is committed at `examples/sample_lease.pdf` so the whole flow runs on `pip install reportlab` plus a Poppler install.

### `auto-document-codebase`

Hand-maintained architecture docs go stale within weeks. This skill regenerates `CODEBASE_DOCS.md` from the source every run: AST-parse Python, regex-parse SQL, PyYAML-or-regex-parse YAML, notebook code cells concatenated then AST-parsed. Output has a coverage summary, a diff-since-last-regen (via a sidecar `.state.json`), a Mermaid dependency diagram, a topo-sorted file index, an undocumented-callables list, a TODO/FIXME index, and per-file sections. Source is **never** inlined; missing docstrings are flagged so they get backfilled at the source rather than duplicated. Scan set is configurable via `--scan` or `AUTODOC_SCAN_DIRS`. Ships stdlib-only.

### `databricks-submit-poll`

For work you're going to run once, or from a shell, or from CI, without wanting to define a persistent Databricks Job. `POST /api/2.1/jobs/runs/submit` with your task JSON, poll `runs/get` until the run leaves the RUNNING pool, print each state transition and the final `run_page_url`. Stdlib-only (`urllib`, no `databricks-sdk` install needed), so it drops into any Python 3.9+ environment. Task payload is passed as a JSON file the script forwards verbatim, so any task shape the Databricks API accepts works.

### `codebase-mapper`

Sub-agent for landing in an unfamiliar repo. Its output is bounded: an overview in two or three sentences, entry points with `file:line`, top-level module responsibilities, a short data-flow summary, and exactly three files a new contributor should read first with one-line justifications. Instructions bias it toward starting wide with `Glob`, following imports outward from entry points, sampling rather than exhausting large directories, and never full-reading files over ~1500 lines. Verbose exploration stays inside the sub-agent's context; only the distilled 60-line map returns to the main thread. Language-agnostic by design.

### `pipeline-reviewer`

For PySpark / Databricks pipeline code. Reviews against exactly five categories: schema drift risks (inferred schemas, `SELECT *`, unpinned Delta merge behavior), partition and shuffle red flags (wide ops without hints, `.repartition(1)` before write, coalesce after skewed transforms), medallion-layer hygiene (business logic in bronze, gold reading bronze, no dedup in silver), MLflow logging completeness (unlogged hyperparameters, missing `set_experiment`, autolog duplication), and cost traps (`.collect()` on unbounded frames, unbroadcast joins, `.count()` without cache). Every finding has a severity (HIGH/MEDIUM/LOW), a `file:line`, and a one-sentence fix. Refuses to expand into style review.

### `databricks-table-eda`

Read-only Unity Catalog table inspector. Given `catalog.schema.table`, returns schema, row count, five to ten sample rows, per-column null rates (sample-based for tables over 10 million rows), partition columns, and last-write timestamp. Uses Databricks MCP tools when one is configured in the session; falls back to raw SQL through any Databricks execute path. Calls out structural surprises like all-null columns, mixed types in STRING fields holding numbers, and unexpected high cardinality. Never issues `INSERT` / `UPDATE` / `DELETE` / `MERGE` / `DROP` / `ALTER`.

### `guard_dangerous_commands.py`

The deterministic side of the capability-tier idea I use in persistent-agent designs. A `PreToolUse` hook against Bash that blocks four patterns before the tool call reaches the shell: `rm -r/-f/--recursive` against an absolute or `$HOME`-rooted path, `git push --force / -f / --force-with-lease`, any redirect or copy/move targeting `.env*`, and SQL DROP / TRUNCATE / DELETE-without-WHERE embedded in a shell command. On block: exit 2 with a stderr message identifying the pattern and quoting the offending command. Malformed input fails open, not closed. 20 test cases pinned in the commit history cover the block list.

### `post_edit_lint.sh`

Cheap continuous feedback loop. A `PostToolUse` hook that runs `ruff check` on any edited Python file, prints findings to stderr, and always exits zero so lint hints surface to the model without blocking the tool call. Non-Python files get a "no linter configured" note and the same zero exit. Under 30 lines. The design decision is the exit code: lint findings belong in the model's context as hints, not as gate failures. Real enforcement belongs in CI, not the edit loop.

### `warn_unpinned_deps.py`

Codifies "pin every dependency version" as a mechanical hint at save time rather than a rule the model has to remember. A `PostToolUse` hook that scans an edited `pyproject.toml`, `requirements.txt`, or `requirements-*.txt` for entries that lack an exact `==X.Y.Z` pin. Handles `[project.dependencies]`, `[dependency-groups]`, and Poetry v1's `[tool.poetry.dependencies]` layout. Uses `tomllib` on Python 3.11+ and falls back to a coarser regex on older versions. Never blocks; findings go to stderr.

### `mlflow-lookup`

Small MCP server so I can ask Claude Code "what's the accuracy on my latest run" without switching to the MLflow UI. Two read-only tools built with `FastMCP` from the official `mcp` Python SDK: `list_runs(experiment_name, max_results=10)` and `get_run(run_id)`. Targets a local MLflow tracking directory by default (`./mlruns`), so no cloud account or auth flow is needed to demo it. Errors return as structured `{"error": "..."}` dicts rather than raised exceptions so the model gets clean feedback. Millisecond epochs from the MLflow API are converted to ISO 8601 UTC at the boundary. A `seed_runs.py` script populates two fake runs so a reviewer can exercise the flow in one minute.

## Setup

**Prerequisites**

- Python 3.9 or newer on PATH (3.11+ recommended for `warn_unpinned_deps.py`'s full `tomllib` path).
- `ruff` on PATH (`pip install ruff`) for `post_edit_lint.sh`.
- `pdftoppm` on PATH (from Poppler) for `pdf-clause-extract`. Install via `brew install poppler` (macOS), `apt install poppler-utils` (Debian / Ubuntu), or `conda install -c conda-forge poppler` / the Poppler-Windows release (Windows).
- `mcp` and `mlflow` in the Python your Claude Code launches: `pip install -r mcp-servers/mlflow-lookup/requirements.txt`.
- `reportlab==4.4.4` **only** if you want to regenerate `examples/sample_lease.pdf`. Not needed to run extraction.

**Environment variables** (copy `.env.example` to `.env` and fill what you need):

| Variable | Used by | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | `pdf-clause-extract` | required |
| `MLFLOW_TRACKING_URI` | `mlflow-lookup` | `./mlruns` |
| `DATABRICKS_HOST`, `DATABRICKS_TOKEN` | `databricks-submit-poll` | required |
| `AUTODOC_SCAN_DIRS` | `auto-document-codebase` | `src` |

**Triggering each piece**

- **Skills** (`daily-briefing`, `pdf-clause-extract`, `auto-document-codebase`, `databricks-submit-poll`): invoked by name or a trigger phrase from Claude Code. Each skill's `SKILL.md` has a one-command demo against `examples/`.
- **Sub-agents** (`codebase-mapper`, `pipeline-reviewer`, `databricks-table-eda`): invoked with `@name` in Claude Code.
- **Hooks**: fire automatically once `.claude/settings.json` is loaded. Restart Claude Code in this repo after cloning so the hook registrations pick up.
- **MCP server**: launched on session start via `.mcp.json`. Seed the tracking store first (`python mcp-servers/mlflow-lookup/seed_runs.py`), then restart Claude Code and ask about the `demo` experiment.

**Cloning**

```
git clone https://github.com/royayon/claude-config.git
cd claude-config
cp .env.example .env
# fill in secrets in .env; it is gitignored
pip install ruff
pip install -r mcp-servers/mlflow-lookup/requirements.txt
```

Then start Claude Code in this directory. Hooks and MCP register on session start.
