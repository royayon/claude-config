#!/usr/bin/env python3
"""auto-document-codebase: regenerate CODEBASE_DOCS.md from workspace files.

Scans directories for Python (.py), Jupyter notebook (.ipynb), SQL (.sql),
and YAML (.yml, .yaml) files. Emits a single Markdown document with
descriptions only. Source code is never inlined; missing docstrings are
flagged so they can be backfilled in the source itself.

Sections written to the output file, in order:
    1. Header (UTC timestamp, do-not-hand-edit note)
    2. Coverage summary
    3. Changes since last regen (diff vs sidecar .state.json)
    4. Mermaid dependency diagram
    5. File index (dependency-ordered)
    6. Undocumented callables list (file:line)
    7. TODO / FIXME / HACK / XXX index
    8. Per-file sections in dependency order

Stdlib only. PyYAML is optional; without it, YAML parsing degrades to a
regex-based extraction of top-level keys.

Config:
    --scan DIR [DIR ...]         Scan set. Falls back to $AUTODOC_SCAN_DIRS
                                 (comma-separated), then to 'src'.
    --output PATH                Output markdown path. Default CODEBASE_DOCS.md.
    --state PATH                 Sidecar state file for diffs.
    --root PATH                  Repo root for module-name computation.

Idempotent and safe to run inside a PostToolUse hook.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


EXCLUDE_DIRS = {
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "__pycache__", ".ipynb_checkpoints",
    "node_modules", "dist", "build",
    ".claude", ".pytest_cache", ".ruff_cache", ".mypy_cache",
}
EXCLUDE_NAMES = {"CODEBASE_DOCS.md", "README.md"}
SUPPORTED_SUFFIXES = {".py", ".ipynb", ".sql", ".yml", ".yaml"}
TODO_KINDS = ("TODO", "FIXME", "HACK", "XXX")


# ---- Python parser -----------------------------------------------------------


def parse_python_source(src: str, path_str: str) -> dict:
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {"error": f"{e.msg} at line {e.lineno}"}
    out: dict = {
        "docstring": ast.get_docstring(tree),
        "imports": [],
        "classes": [],
        "functions": [],
        "undocumented": [],
    }
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out["imports"].append(_safe_unparse(node))
        elif isinstance(node, ast.ClassDef):
            cls = {
                "name": node.name,
                "line": node.lineno,
                "bases": [_safe_unparse(b) for b in node.bases],
                "doc": ast.get_docstring(node),
                "methods": [],
            }
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(item)
                    cls["methods"].append(
                        {"name": item.name, "line": item.lineno, "doc": doc}
                    )
                    if not doc:
                        out["undocumented"].append(
                            {"path": path_str, "line": item.lineno,
                             "name": f"{node.name}.{item.name}"}
                        )
            out["classes"].append(cls)
            if not cls["doc"]:
                out["undocumented"].append(
                    {"path": path_str, "line": node.lineno,
                     "name": f"class {node.name}"}
                )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            out["functions"].append(
                {"name": node.name, "line": node.lineno,
                 "signature": _fn_signature(node), "doc": doc}
            )
            if not doc:
                out["undocumented"].append(
                    {"path": path_str, "line": node.lineno, "name": node.name}
                )
    return out


def _safe_unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _fn_signature(node) -> str:
    args = [a.arg for a in node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


def parse_python_file(path: Path, display: str) -> dict:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": str(e)}
    return parse_python_source(src, display)


# ---- Notebook parser ---------------------------------------------------------


def parse_notebook(path: Path, display: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}
    code_lines: list[str] = []
    magic_deps: list[str] = []
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("%run", "# MAGIC %run")):
                m = re.search(r"%run\s+(\S+)", stripped)
                if m:
                    magic_deps.append(m.group(1))
            code_lines.append(line)
    parsed = parse_python_source("\n".join(code_lines), display)
    parsed["magic_run_deps"] = magic_deps
    return parsed


# ---- SQL parser --------------------------------------------------------------


_SQL_CREATE_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(TABLE|VIEW|FUNCTION|PROCEDURE|MATERIALIZED\s+VIEW)\s+"
    r"([A-Za-z_][\w.$]*)",
    re.IGNORECASE,
)


def parse_sql_file(path: Path) -> dict:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": str(e)}
    desc_lines: list[str] = []
    for line in src.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("--"):
            desc_lines.append(s.lstrip("- ").strip())
            continue
        break
    creates: list[dict] = []
    for m in _SQL_CREATE_RE.finditer(src):
        line_no = src[: m.start()].count("\n") + 1
        creates.append({
            "kind": re.sub(r"\s+", " ", m.group(1).upper()),
            "name": m.group(2),
            "line": line_no,
        })
    return {"description": "\n".join(desc_lines), "creates": creates}


# ---- YAML parser -------------------------------------------------------------


def parse_yaml_file(path: Path) -> dict:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": str(e)}
    try:
        import yaml
    except ImportError:
        keys = re.findall(r"^([A-Za-z_][\w-]*)\s*:", src, re.MULTILINE)
        return {"top_keys": sorted(set(keys)), "pairs": [], "yaml_lib": False}
    try:
        data = yaml.safe_load(src)
    except yaml.YAMLError as e:
        return {"error": str(e)}
    return {"pairs": _yaml_name_desc_pairs(data, ""), "yaml_lib": True}


def _yaml_name_desc_pairs(data, prefix: str) -> list:
    pairs: list = []
    if isinstance(data, dict):
        name = data.get("name") if isinstance(data.get("name"), str) else None
        desc = data.get("description") if isinstance(data.get("description"), str) else None
        if name or desc:
            pairs.append({"path": prefix or "root", "name": name, "description": desc})
        for k, v in data.items():
            new_prefix = f"{prefix}.{k}" if prefix else str(k)
            pairs.extend(_yaml_name_desc_pairs(v, new_prefix))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_prefix = f"{prefix}[{i}]" if prefix else f"[{i}]"
            pairs.extend(_yaml_name_desc_pairs(item, new_prefix))
    return pairs


# ---- TODO extractor ----------------------------------------------------------


def extract_todos(path: Path, display: str) -> list:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    todos: list = []
    for i, line in enumerate(src.splitlines(), 1):
        for kind in TODO_KINDS:
            m = re.search(rf"\b({kind})\b[:\s](.+?)$", line)
            if m:
                todos.append({
                    "file": display, "line": i, "kind": kind,
                    "text": m.group(2).strip(),
                })
                break
    return todos


# ---- File discovery ---------------------------------------------------------


def discover_files(scan_dirs: list, root: Path) -> list:
    files: set = set()
    for d in scan_dirs:
        p = Path(d)
        base = (root / p).resolve() if not p.is_absolute() else p.resolve()
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            # Excludes apply only BELOW the scan base, so a caller can scan
            # into .claude/ explicitly without the .claude-in-parts rule
            # tripping.
            try:
                rel_parts = f.relative_to(base).parts
            except ValueError:
                rel_parts = f.parts
            if any(part in EXCLUDE_DIRS for part in rel_parts[:-1]):
                continue
            if f.name in EXCLUDE_NAMES:
                continue
            if f.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            files.add(f)
    return sorted(files)


# ---- Dep graph and topo sort ------------------------------------------------


def build_dep_graph(files_info: dict, root: Path) -> dict:
    # `files_info` keys are relative POSIX paths already, so the module name
    # is just the parts of the path minus the suffix.
    module_to_file: dict = {}
    for path_str in files_info:
        p = Path(path_str)
        if p.suffix != ".py":
            continue
        module = ".".join(p.with_suffix("").parts)
        module_to_file[module] = path_str
    graph: dict = defaultdict(set)
    for path_str, info in files_info.items():
        graph[path_str]  # ensure node exists
        for imp in info.get("imports") or []:
            m = re.match(r"(?:from\s+([\w.]+)|import\s+([\w.,\s]+))", imp)
            if not m:
                continue
            candidates = []
            if m.group(1):
                candidates.append(m.group(1))
            if m.group(2):
                for piece in m.group(2).split(","):
                    piece = piece.strip().split(" as ")[0].strip()
                    if piece:
                        candidates.append(piece)
            for mod in candidates:
                parts = mod.split(".")
                for cut in range(len(parts), 0, -1):
                    key = ".".join(parts[:cut])
                    if key in module_to_file and module_to_file[key] != path_str:
                        graph[path_str].add(module_to_file[key])
                        break
        for target in info.get("magic_run_deps") or []:
            wanted = Path(target).with_suffix(".py").name
            for other in files_info:
                if other != path_str and Path(other).name == wanted:
                    graph[path_str].add(other)
    return {k: sorted(v) for k, v in graph.items()}


def topo_sort(graph: dict) -> list:
    """Kahn: emit deps before dependents. Leftover cycles get alpha order."""
    indeg: dict = defaultdict(int)
    for node in graph:
        indeg[node]
    reverse: dict = defaultdict(list)
    for node, deps in graph.items():
        for d in deps:
            indeg[node] += 1
            reverse[d].append(node)
    ready = sorted([n for n in graph if indeg[n] == 0])
    order: list = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in reverse.get(n, []):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort()
    leftover = sorted([n for n in graph if n not in order])
    return order + leftover


# ---- State snapshot / diff --------------------------------------------------


def build_snapshot(files_info: dict) -> dict:
    snap: dict = {}
    for path_str, info in files_info.items():
        items: list = []
        for cls in info.get("classes") or []:
            items.append(f"class {cls['name']}")
            for meth in cls.get("methods") or []:
                items.append(f"method {cls['name']}.{meth['name']}")
        for fn in info.get("functions") or []:
            items.append(f"def {fn['name']}")
        for c in info.get("creates") or []:
            items.append(f"{c['kind']} {c['name']}")
        snap[path_str] = sorted(set(items))
    return snap


def diff_snapshots(prev: dict, curr: dict) -> dict:
    prev_files = set(prev)
    curr_files = set(curr)
    added_files = sorted(curr_files - prev_files)
    removed_files = sorted(prev_files - curr_files)
    prev_pairs = {(f, item) for f, items in prev.items() for item in items}
    curr_pairs = {(f, item) for f, items in curr.items() for item in items}
    added = [
        {"file": f, "item": i}
        for (f, i) in sorted(curr_pairs - prev_pairs)
        if f not in set(added_files)
    ]
    removed = [
        {"file": f, "item": i}
        for (f, i) in sorted(prev_pairs - curr_pairs)
        if f not in set(removed_files)
    ]
    return {
        "added_files": added_files,
        "removed_files": removed_files,
        "added": added,
        "removed": removed,
    }


# ---- Rendering --------------------------------------------------------------


def render(files_info: dict, order: list, graph: dict, todos: list, diff: dict) -> str:
    parts: list = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    parts.append("# Codebase documentation")
    parts.append("")
    parts.append(
        f"_Regenerated {now}. Descriptions only, source is not inlined. "
        "Do not edit by hand; this file is overwritten on every run._"
    )
    parts.append("")

    total_classes = sum(len(i.get("classes") or []) for i in files_info.values())
    total_fns = sum(len(i.get("functions") or []) for i in files_info.values())
    total_sql = sum(len(i.get("creates") or []) for i in files_info.values())
    total_undoc = sum(len(i.get("undocumented") or []) for i in files_info.values())
    parts.append("## Coverage")
    parts.append("")
    parts.append(f"- Files: {len(files_info)}")
    parts.append(f"- Classes: {total_classes}")
    parts.append(f"- Functions / methods: {total_fns}")
    parts.append(f"- SQL definitions: {total_sql}")
    parts.append(f"- Undocumented callables: {total_undoc}")
    parts.append(f"- TODOs: {len(todos)}")
    parts.append("")

    parts.append("## Changes since last regen")
    parts.append("")
    if not any([diff["added_files"], diff["removed_files"], diff["added"], diff["removed"]]):
        parts.append("_No structural changes since the previous snapshot._")
    else:
        for f in diff["added_files"]:
            parts.append(f"- Added file: `{f}`")
        for f in diff["removed_files"]:
            parts.append(f"- Removed file: `{f}`")
        for entry in diff["added"]:
            parts.append(f"- Added: `{entry['item']}` in `{entry['file']}`")
        for entry in diff["removed"]:
            parts.append(f"- Removed: `{entry['item']}` in `{entry['file']}`")
    parts.append("")

    parts.append("## Dependency diagram")
    parts.append("")
    parts.append("```mermaid")
    parts.append("flowchart LR")
    node_id = {p: f"n{i}" for i, p in enumerate(files_info)}
    for p, nid in node_id.items():
        label = Path(p).name.replace('"', "'")
        parts.append(f'  {nid}["{label}"]')
    for src, deps in graph.items():
        for d in deps:
            if d in node_id:
                parts.append(f"  {node_id[d]} --> {node_id[src]}")
    parts.append("```")
    parts.append("")

    parts.append("## File index (dependency order)")
    parts.append("")
    for path in order:
        kind = Path(path).suffix.lstrip(".").lower() or "file"
        parts.append(f"- [{kind}] `{path}`")
        deps = graph.get(path) or []
        if deps:
            dep_names = ", ".join(f"`{Path(d).name}`" for d in deps)
            parts.append(f"  - depends on: {dep_names}")
    parts.append("")

    parts.append("## Undocumented callables")
    parts.append("")
    undoc: list = []
    for info in files_info.values():
        undoc.extend(info.get("undocumented") or [])
    if not undoc:
        parts.append("_None._")
    else:
        for item in undoc:
            parts.append(f"- `{item['path']}:{item['line']}` `{item['name']}`")
    parts.append("")

    parts.append("## TODO / FIXME / HACK / XXX")
    parts.append("")
    if not todos:
        parts.append("_None._")
    else:
        grouped: dict = defaultdict(list)
        for t in todos:
            grouped[t["kind"]].append(t)
        for kind in TODO_KINDS:
            items = grouped.get(kind) or []
            if not items:
                continue
            parts.append(f"### {kind}")
            for t in items:
                parts.append(f"- `{t['file']}:{t['line']}` {t['text']}")
            parts.append("")

    parts.append("## Files")
    parts.append("")
    for path in order:
        info = files_info[path]
        parts.append(f"### `{path}`")
        parts.append("")
        if info.get("error"):
            parts.append(f"Parse error: {info['error']}")
            parts.append("")
            continue
        if info.get("docstring"):
            parts.append(info["docstring"])
            parts.append("")
        elif info.get("description"):
            parts.append(info["description"])
            parts.append("")
        elif info.get("pairs"):
            for pair in info["pairs"]:
                name = pair["name"] or "(unnamed)"
                desc = pair["description"] or ""
                parts.append(f"- **{pair['path']}**: `{name}` {desc}".rstrip())
            parts.append("")
        elif info.get("top_keys"):
            keys = ", ".join(f"`{k}`" for k in info["top_keys"])
            parts.append(f"Top-level keys: {keys}")
            parts.append("")
        else:
            parts.append("_No module-level description._")
            parts.append("")

        for cls in info.get("classes") or []:
            bases = f"({', '.join(cls['bases'])})" if cls.get("bases") else ""
            parts.append(f"#### class `{cls['name']}{bases}` at `{path}:{cls['line']}`")
            parts.append("")
            if cls.get("doc"):
                parts.append(cls["doc"])
            else:
                parts.append("_no class docstring._")
            parts.append("")
            for meth in cls.get("methods") or []:
                first_line = (meth.get("doc") or "").splitlines()[0] if meth.get("doc") else "_no docstring_"
                parts.append(f"- `{meth['name']}` (line {meth['line']}): {first_line}")
            parts.append("")

        for fn in info.get("functions") or []:
            parts.append(f"#### `{fn['signature']}` at `{path}:{fn['line']}`")
            parts.append("")
            if fn.get("doc"):
                parts.append(fn["doc"])
            else:
                parts.append("_no docstring._")
            parts.append("")

        for c in info.get("creates") or []:
            parts.append(f"- **{c['kind']}** `{c['name']}` (line {c['line']})")
        if info.get("creates"):
            parts.append("")

    return "\n".join(parts) + "\n"


# ---- Main -------------------------------------------------------------------


def scan_dirs_from_args(cli_scan, env) -> list:
    if cli_scan:
        return list(cli_scan)
    env_val = (env.get("AUTODOC_SCAN_DIRS") or "").strip()
    if env_val:
        return [d.strip() for d in env_val.split(",") if d.strip()]
    return ["src"]


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, sort_keys=True, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", nargs="+", metavar="DIR",
                        help="Directories to scan (default: 'src' or $AUTODOC_SCAN_DIRS)")
    parser.add_argument("--output", default="CODEBASE_DOCS.md")
    parser.add_argument("--state",
                        default=".claude/skills/auto-document-codebase/.state.json")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    scan = scan_dirs_from_args(args.scan, os.environ)
    files = discover_files(scan, root)
    output_path = Path(args.output)
    state_path = Path(args.state)

    if not files:
        output_path.write_text(
            "# Codebase documentation\n\n"
            f"_Nothing found under: {', '.join(scan)}._\n",
            encoding="utf-8",
        )
        save_state(state_path, {})
        print(f"[auto-document-codebase] no files matched under {scan}", file=sys.stderr)
        return 0

    files_info: dict = {}
    all_todos: list = []
    for f in files:
        try:
            display = f.relative_to(root).as_posix()
        except ValueError:
            display = f.as_posix()
        suffix = f.suffix.lower()
        if suffix == ".py":
            info = parse_python_file(f, display)
        elif suffix == ".ipynb":
            info = parse_notebook(f, display)
        elif suffix == ".sql":
            info = parse_sql_file(f)
        elif suffix in (".yml", ".yaml"):
            info = parse_yaml_file(f)
        else:
            continue
        files_info[display] = info
        all_todos.extend(extract_todos(f, display))

    graph = build_dep_graph(files_info, root)
    order = topo_sort(graph)
    curr = build_snapshot(files_info)
    prev = load_state(state_path)
    diff = diff_snapshots(prev, curr)

    output_path.write_text(render(files_info, order, graph, all_todos, diff), encoding="utf-8")
    save_state(state_path, curr)
    print(
        f"[auto-document-codebase] wrote {output_path} "
        f"({len(files_info)} files, {sum(len(v) for v in curr.values())} items)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
