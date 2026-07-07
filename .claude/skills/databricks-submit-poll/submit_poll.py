#!/usr/bin/env python3
"""databricks-submit-poll: submit a one-off Databricks run, poll to terminal state.

Uses /api/2.1/jobs/runs/submit (one-off run, no persistent job created) then
polls /api/2.1/jobs/runs/get until the run leaves the RUNNING / PENDING pool.
Prints state transitions along the way; exits:
  0  SUCCESS
  1  FAILED / CANCELED / INTERNAL_ERROR / other terminal-failure
  2  poll timeout
  3  config error (missing env vars, bad task JSON, HTTP error before submit)

Auth via env vars DATABRICKS_HOST (e.g. https://your.cloud.databricks.com) and
DATABRICKS_TOKEN (a personal access token). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TERMINAL_STATES = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
SUCCESS_RESULTS = {"SUCCESS"}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _post(host: str, token: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{host.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(host: str, token: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{host.rstrip('/')}{path}", headers=_headers(token), method="GET"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def submit(host: str, token: str, task_body: dict) -> int:
    result = _post(host, token, "/api/2.1/jobs/runs/submit", task_body)
    return int(result["run_id"])


def poll(host: str, token: str, run_id: int, interval: int, timeout: int) -> dict:
    """Poll until terminal state or timeout. Returns the final run object."""
    start = time.monotonic()
    last_state: tuple[str, str] | None = None
    while True:
        run = _get(host, token, f"/api/2.1/jobs/runs/get?run_id={run_id}")
        state = run.get("state") or {}
        life_cycle = state.get("life_cycle_state", "?")
        result = state.get("result_state") or ""
        msg = state.get("state_message") or ""
        current = (life_cycle, result)
        if current != last_state:
            line = f"[{run_id}] {life_cycle}"
            if result:
                line += f" / {result}"
            if msg:
                line += f": {msg}"
            print(line, flush=True)
            last_state = current
        if life_cycle in TERMINAL_STATES:
            return run
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"Run {run_id} did not reach terminal state within {timeout}s")
        time.sleep(interval)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task_json", help="Path to a JSON file matching the runs/submit request body")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between polls (default 10)")
    parser.add_argument("--timeout", type=int, default=1800, help="Max total wait, seconds (default 1800)")
    args = parser.parse_args(argv)

    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")
    if not host or not token:
        print("error: DATABRICKS_HOST and DATABRICKS_TOKEN must be set", file=sys.stderr)
        return 3

    try:
        with open(args.task_json) as f:
            task_body = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: could not read {args.task_json}: {e}", file=sys.stderr)
        return 3

    try:
        run_id = submit(host, token, task_body)
        print(f"[submitted] run_id={run_id}", flush=True)
        run = poll(host, token, run_id, args.interval, args.timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        print(f"error: Databricks API returned {e.code}: {detail}", file=sys.stderr)
        return 1 if e.code >= 500 else 3
    except TimeoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except urllib.error.URLError as e:
        print(f"error: could not reach {host}: {e.reason}", file=sys.stderr)
        return 3

    result = (run.get("state") or {}).get("result_state") or ""
    url = run.get("run_page_url") or ""
    print(f"[final] result={result or 'UNKNOWN'} url={url}")
    return 0 if result in SUCCESS_RESULTS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
