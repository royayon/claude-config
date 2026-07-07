#!/usr/bin/env python3
"""PreToolUse guard hook for destructive Bash commands.

Registered in .claude/settings.json against the Bash tool. Claude Code invokes
this script with a JSON payload on stdin; we exit 2 with a stderr message to
block the tool call and surface the reason to the model, or exit 0 to allow.

Design note: this is the deterministic side of the capability-tier idea I use
in persistent-agent designs. Model-side prompt hints are advisory; a hook is
mechanically unavoidable from Claude Code, regardless of what the transcript
says. Destructive verbs get a hard gate here so the model can only reach them
by first getting past this file.

Patterns blocked:
  1. `rm` with -r / -f / --recursive / --force against an absolute or
     home-rooted path. Project-relative paths are still allowed.
  2. `git push` with --force, -f, or --force-with-lease. Force-pushing
     rewrites remote history.
  3. Any redirect or copy/move whose target is .env (or .env.local, etc.).
     The file is gitignored on purpose; editing it should be manual.
  4. SQL DROP / TRUNCATE / unbounded DELETE embedded in a shell command.
     Best effort against `-c "..."` args and heredocs; false positives are
     cheaper than an accidental table drop.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional


# Each `rm` invocation is scoped by shell separators (start-of-line, `;`, `&`,
# `|`) so `git rm` in a longer pipeline is not misread as a bare `rm`.
_RM_INVOCATION = re.compile(r"(?:^|[;&|]\s*)\s*rm\s+([^\n;&|]*)", re.MULTILINE)
_RM_FLAG = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*[rRfF]|--recursive|--force)\b")
_RM_TARGET = re.compile(r"(?:^|\s)(?:/|~|\$HOME|\$\{HOME\})")


def rm_dangerous(cmd: str) -> bool:
    for m in _RM_INVOCATION.finditer(cmd):
        args = m.group(1)
        if _RM_FLAG.search(args) and _RM_TARGET.search(args):
            return True
    return False


def check(cmd: str) -> Optional[str]:
    if rm_dangerous(cmd):
        return (
            "rm with -r/-f/--recursive against an absolute or home-rooted path "
            "is blocked. Use a project-relative path."
        )
    if re.search(r"\bgit\s+push\b", cmd) and re.search(
        r"\s(?:-f\b|--force\b|--force-with-lease\b)", cmd
    ):
        return (
            "git push --force / -f / --force-with-lease is blocked. "
            "Force-pushing rewrites remote history."
        )
    if re.search(
        r"(?:>\s*|>>\s*|tee\s+(?:-a\s+)?|cp\s+\S+\s+|mv\s+\S+\s+)(?:\./)?\.env(?:\.[A-Za-z0-9_.-]+)?\b",
        cmd,
    ):
        return (
            "Writing to .env is blocked. Edit .env by hand; the file is "
            "gitignored on purpose."
        )
    # SQL: split the DROP/TRUNCATE test from the DELETE-without-WHERE test.
    # Using a negative lookahead inside a single regex lets Python's backtracker
    # settle on a shorter \w+ match to satisfy the lookahead, which produced
    # false positives on well-scoped DELETEs. Two regexes, no ambiguity.
    sql_hard = re.search(
        r"\b(?:DROP\s+(?:TABLE|DATABASE|SCHEMA|INDEX)|TRUNCATE\s+TABLE)\b",
        cmd,
        re.IGNORECASE,
    )
    sql_delete = re.search(r"\bDELETE\s+FROM\s+\w+", cmd, re.IGNORECASE)
    sql_delete_where = re.search(
        r"\bDELETE\s+FROM\s+\w+\s+WHERE\b", cmd, re.IGNORECASE
    )
    if sql_hard or (sql_delete and not sql_delete_where):
        return (
            "SQL DROP / TRUNCATE / unbounded DELETE detected. Add a WHERE "
            "clause, or run this outside Claude Code."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Malformed payload = fail open. A wedged hook that blocks every
        # Bash call is worse than missing one edge case here.
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return 0

    reason = check(command)
    if reason is None:
        return 0

    print(f"[guard_dangerous_commands] Blocked: {reason}", file=sys.stderr)
    print(f"[guard_dangerous_commands] Offending command: {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
