#!/usr/bin/env python3
"""PostToolUse hook: warn on unpinned Python dependencies.

Fires on Edit / Write / MultiEdit. If the edited file is `pyproject.toml`,
`requirements.txt`, or `requirements-<label>.txt`, scan for entries that
lack an exact `==X.Y.Z` pin and print warnings to stderr. Never blocks.

Design note: this codifies "pin every dependency" as a mechanical hint on
save, rather than something the model has to remember. Unpinned specs cause
invisible version drift; long-running automated jobs are the usual victims.
The hook makes the drift visible at the point of the change.

What counts as pinned:
  - `pkg==1.2.3`                    OK
  - `pkg==1.2.3; python_version>='3.9'`   OK (env marker ignored)
  - `pkg==1.2.*`                    FLAGGED (spec-level wildcard)
  - `pkg`, `pkg>=1.2`, `pkg~=1.2`, `pkg^1.2`  FLAGGED (bare or range)

Skipped lines:
  - blanks, `#` comments
  - `-r other.txt`, `-e ./local`, VCS / http URLs
  - Poetry `python` entry
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def is_pinned(spec: str) -> bool:
    m = re.search(r"==\s*([0-9A-Za-z.\-+]+)", spec)
    if not m:
        return False
    return "*" not in m.group(1)


def parse_requirement_line(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith(("-r", "-e", "--", "http://", "https://", "git+")):
        return None
    return s.split(";", 1)[0].strip() or None


def scan_requirements(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for i, raw in enumerate(text.splitlines(), 1):
        req = parse_requirement_line(raw)
        if req is None:
            continue
        if not is_pinned(req):
            findings.append(f"{path}:{i}: unpinned `{req}`; pin to `==X.Y.Z`")
    return findings


def _pyproject_deps(data: dict) -> list[str]:
    """Extract every requirement string from a parsed pyproject.toml dict."""
    out: list[str] = []
    project = data.get("project") or {}
    for dep in project.get("dependencies") or []:
        if isinstance(dep, str):
            out.append(dep)
    for _, entries in (data.get("dependency-groups") or {}).items():
        for dep in entries or []:
            if isinstance(dep, str):
                out.append(dep)
    # Poetry v1 layout: [tool.poetry.dependencies] = { name = "version" }
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    for name, ver in poetry.items():
        if name == "python" or not isinstance(ver, str):
            continue
        # Prepend `==` only if the caller did not already write an operator.
        if re.match(r"^\s*(==|>=|<=|~=|!=|\^|<|>)", ver):
            out.append(f"{name}{ver}")
        else:
            out.append(f"{name}=={ver}")
    return out


def scan_pyproject(path: Path) -> list[str]:
    findings: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import tomllib  # Py 3.11+
    except ImportError:
        # Regex fallback for older Pythons: crude, misses group tables.
        # Every quoted string that starts with a package-name character and
        # is not exact-pinned gets flagged. False positives are noisy but
        # not blocking, and the "upgrade Python" hint is worth the noise.
        for m in re.finditer(r'"([A-Za-z][^"]{0,200})"', text):
            spec = m.group(1)
            if not is_pinned(spec):
                findings.append(f"{path}: unpinned `{spec}`; pin to `==X.Y.Z`")
        return findings

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return findings
    for spec in _pyproject_deps(data):
        if not is_pinned(spec):
            findings.append(f"{path}: unpinned `{spec}`; pin to `==X.Y.Z`")
    return findings


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = ((payload.get("tool_input") or {}).get("file_path") or "").strip()
    if not file_path:
        return 0
    path = Path(file_path)
    if not path.is_file():
        return 0

    name = path.name
    if name == "pyproject.toml":
        findings = scan_pyproject(path)
    elif name == "requirements.txt" or re.fullmatch(r"requirements-[\w-]+\.txt", name):
        findings = scan_requirements(path)
    else:
        return 0

    for line in findings:
        print(f"[warn_unpinned_deps] {line}", file=sys.stderr)
    return 0  # never block


if __name__ == "__main__":
    sys.exit(main())
