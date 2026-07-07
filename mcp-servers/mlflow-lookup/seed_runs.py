#!/usr/bin/env python3
"""Seed a local MLflow tracking directory with two fake runs so a reviewer
can demo the mlflow-lookup MCP server in one minute.

Idempotent-ish: reruns append additional runs to the same experiment.
Delete `./mlruns/` (or wherever MLFLOW_TRACKING_URI points) to reset.

Usage:
    python mcp-servers/mlflow-lookup/seed_runs.py
"""
from __future__ import annotations

import os
import random

# See server.py for context; MLflow 3.x requires this opt-in for the
# filesystem backend and the brief specifies `./mlruns` as the default.
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import mlflow  # noqa: E402

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "./mlruns")
EXPERIMENT = "demo"

RUNS = [
    {
        "name": "baseline-rf",
        "params": {
            "model": "RandomForest",
            "n_estimators": "100",
            "max_depth": "10",
        },
        "metrics": {"accuracy": 0.842, "f1": 0.821, "roc_auc": 0.898},
    },
    {
        "name": "boosted-gbm",
        "params": {
            "model": "GradientBoosting",
            "n_estimators": "300",
            "learning_rate": "0.05",
        },
        "metrics": {"accuracy": 0.867, "f1": 0.849, "roc_auc": 0.912},
    },
]


def main() -> None:
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    rng = random.Random(42)
    for cfg in RUNS:
        with mlflow.start_run(run_name=cfg["name"]):
            for k, v in cfg["params"].items():
                mlflow.log_param(k, v)
            for k, v in cfg["metrics"].items():
                mlflow.log_metric(k, v)
            mlflow.log_metric("training_time_sec", rng.uniform(10, 60))
    print(
        f"seeded {len(RUNS)} runs in experiment {EXPERIMENT!r} at {TRACKING_URI}"
    )


if __name__ == "__main__":
    main()
