---
name: databricks-submit-poll
description: "Submit a one-off Databricks run via the jobs/runs/submit API and poll to terminal state. Use for ad-hoc job execution without creating a persistent job. Prints state transitions and the final run URL. Requires DATABRICKS_HOST and DATABRICKS_TOKEN in env."
---

# databricks-submit-poll

Fire-and-poll for one-off Databricks work.

## When to use

- You want to run a notebook, a Python task, or a JAR once without creating a permanent Databricks Job.
- You want a script you can invoke from CI, from a shell, or from Claude Code, that blocks until the run finishes and reports result state plus URL.
- You do not need workflow orchestration (retries, schedules, dependencies). For those, define a proper Databricks Job.

## What it does

1. `POST /api/2.1/jobs/runs/submit` with the task body you supply as JSON.
2. Poll `GET /api/2.1/jobs/runs/get?run_id=...` every N seconds (default 10).
3. Print each state transition (`PENDING → RUNNING → TERMINATED / SUCCESS`).
4. Exit 0 on `SUCCESS`, 1 on `FAILED` / `CANCELED` / `INTERNAL_ERROR` / other, 2 on timeout, 3 on config error.

Stdlib only — no `databricks-sdk` install needed. Python 3.9+.

## Usage

Set env vars (see `.env.example` at the repo root):

```
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi...
```

Then:

```
python .claude/skills/databricks-submit-poll/submit_poll.py \
  .claude/skills/databricks-submit-poll/example_task.json \
  --interval 5 --timeout 900
```

## Task JSON

The file passed as `task_json` must match the `jobs/runs/submit` request body. See `example_task.json` for a minimal notebook-task run against a new cluster. For other task shapes (`spark_python_task`, `spark_jar_task`, `spark_submit_task`, `sql_task`, `pipeline_task`), consult the Databricks REST reference — the script does not restrict the payload; it forwards whatever JSON you provide.

## Notes

- Uses `urllib` from the stdlib rather than `requests`, so no extra installs are needed. In production, the Databricks SDK (`databricks-sdk`) is the recommended path — it handles retries, pagination, and richer error types.
- Timeouts are total wall-clock, not per-poll.
- The `run_page_url` in the final line is your fastest path to logs.
