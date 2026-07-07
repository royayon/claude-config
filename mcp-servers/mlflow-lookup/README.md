# mlflow-lookup MCP server

Small MCP server that exposes two read-only tools over stdio, letting Claude Code query a local MLflow tracking store without switching to the MLflow UI.

## Tools

- `list_runs(experiment_name, max_results=10)`: recent runs in an experiment, most recent first, with their params and metrics.
- `get_run(run_id)`: full detail for one run: params, metrics, tags, artifact paths.

## Prerequisites

Python 3.9+ on PATH. Install the two dependencies (`mcp` and `mlflow`) into whatever Python your Claude Code launches:

    pip install -r mcp-servers/mlflow-lookup/requirements.txt

## Demo in one minute

1. Seed two fake runs into a fresh local tracking directory:

        python mcp-servers/mlflow-lookup/seed_runs.py

    This creates `./mlruns/` under the repo root with an experiment called `demo` containing two runs: `baseline-rf` and `boosted-gbm`, each with a handful of params and metrics.

2. Restart Claude Code in this repo. `.mcp.json` at the repo root registers `mlflow-lookup` on stdio; Claude Code launches the server on session start.

3. In Claude Code, ask something like: *"list the runs in the demo experiment"*. The model calls `list_runs("demo")` and gets back both runs with their accuracy / f1 / roc_auc. Ask *"show the full detail on the boosted run"* and it calls `get_run` with the id from the first response.

## Configuration

`MLFLOW_TRACKING_URI`: where the server reads from. Defaults to `./mlruns`. Set to a `file:` URL to use a specific directory, `sqlite:///mlflow.db` for a SQLite-backed store, or an `http(s)://` URL for a remote MLflow tracking server. The env var must be visible to whichever process Claude Code launches for the MCP server; the easiest way is to export it in the shell you launched Claude Code from.

## Design notes worth reading

- **Stdio transport**. Zero network setup, no port to allocate, no auth. Claude Code launches the server as a subprocess and talks JSON-RPC over its stdin/stdout.
- **`FastMCP`, not the low-level `Server`**. The `@mcp.tool()` decorator turns a Python function into an MCP tool with schema derived from type hints. Type-annotate every arg; keep return values JSON-serializable.
- **Read-only surface**. No `create_experiment`, no `log_metric`, no `delete_run`. If you want write access, use the mlflow CLI or SDK directly. Keeping the tool surface small keeps the model's failure modes small.
- **Errors are structured, not raised**. Both tools return `{"error": "..."}` on lookup failure. The model handles that shape better than a stack trace forwarded through the MCP transport.
- **ISO 8601 timestamps**. MLflow returns millisecond epochs; those are technically correct but hostile to a reader. Converted at the boundary.
