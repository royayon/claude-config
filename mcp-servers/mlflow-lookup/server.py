#!/usr/bin/env python3
"""mlflow-lookup: MCP server exposing two read-only tools over stdio.

Tools:
    list_runs(experiment_name, max_results=10)
        Return recent runs in an experiment, most recent first.
    get_run(run_id)
        Return params, metrics, tags, and artifact paths for one run.

The tracking store is a local MLflow directory (default `./mlruns`) so no
cloud account or auth flow is needed. Set MLFLOW_TRACKING_URI to point
elsewhere: a `file:` URL, `sqlite:///mlflow.db`, or an http(s) tracking
server. Declared in `.mcp.json` at the repo root; Claude Code launches
this on session start over stdio.

Design decisions worth noticing:
    - Read-only. No `create_experiment`, no `log_*`. If you want to
      write, use the mlflow CLI or SDK directly. This makes the surface
      area small and safe to expose to an agent.
    - Errors are returned as dicts with an `error` key rather than
      raised, so the model sees a structured failure instead of a stack
      trace passed through the MCP framing.
    - Timestamps are converted to ISO 8601 UTC strings; the raw
      millisecond epochs MLflow returns are technically correct but
      hostile to a reader.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

# MLflow 3.x refuses the filesystem backend unless this opt-in is set.
# The brief specifies `./mlruns` as the default tracking URI, so we quietly
# opt in here rather than force every reviewer to know about the deprecation.
# Users who point MLFLOW_TRACKING_URI at sqlite or a remote server are
# unaffected.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import mlflow  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mlflow.exceptions import MlflowException  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "./mlruns")
mlflow.set_tracking_uri(TRACKING_URI)

mcp = FastMCP("mlflow-lookup")


def _client() -> MlflowClient:
    return MlflowClient(tracking_uri=TRACKING_URI)


def _iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat()


@mcp.tool()
def list_runs(experiment_name: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Return recent runs in an experiment, ordered most-recent-first.

    Args:
        experiment_name: The MLflow experiment name (e.g. "demo").
        max_results: Cap on the number of runs returned. Default 10.

    Returns:
        A list of dicts, one per run, containing run_id, run_name, status,
        start_time / end_time (ISO 8601 UTC), and the run's params + metrics.
        On lookup failure a single-element list with an `error` key is
        returned so the model gets structured feedback.
    """
    client = _client()
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        return [{"error": f"experiment not found: {experiment_name!r}"}]
    try:
        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            max_results=max_results,
            order_by=["start_time DESC"],
        )
    except MlflowException as e:
        return [{"error": str(e)}]
    return [
        {
            "run_id": r.info.run_id,
            "run_name": r.info.run_name,
            "status": r.info.status,
            "start_time": _iso(r.info.start_time),
            "end_time": _iso(r.info.end_time),
            "params": dict(r.data.params),
            "metrics": dict(r.data.metrics),
        }
        for r in runs
    ]


@mcp.tool()
def get_run(run_id: str) -> dict[str, Any]:
    """Return params, metrics, tags, and artifact paths for one run.

    Args:
        run_id: The MLflow run_id (a 32-char hex string).

    Returns:
        Full run detail as a dict. If the run does not exist, returns
        `{"error": "..."}` so the model gets structured feedback rather
        than a raised exception.
    """
    client = _client()
    try:
        run = client.get_run(run_id)
    except MlflowException as e:
        return {"error": str(e)}
    try:
        artifacts = [a.path for a in client.list_artifacts(run_id)]
    except MlflowException as e:
        artifacts = [f"error listing artifacts: {e}"]
    return {
        "run_id": run.info.run_id,
        "run_name": run.info.run_name,
        "experiment_id": run.info.experiment_id,
        "status": run.info.status,
        "start_time": _iso(run.info.start_time),
        "end_time": _iso(run.info.end_time),
        "params": dict(run.data.params),
        "metrics": dict(run.data.metrics),
        "tags": dict(run.data.tags),
        "artifacts": artifacts,
    }


if __name__ == "__main__":
    mcp.run()
