#!/usr/bin/env python3
"""pdf-clause-extract: rasterize a PDF, ask Claude to extract clauses per page,
validate the JSON, write a CSV.

Usage:
    python extract.py <input.pdf> <output.csv> [--dpi 200] [--model MODEL]

Prerequisites:
    - pdftoppm on PATH (Poppler)
    - ANTHROPIC_API_KEY in the environment

Exit codes:
    0  wrote CSV successfully
    1  API call or JSON validation failure
    2  timeout
    3  config error: missing env var, missing input, missing pdftoppm
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
API_VERSION = "2023-06-01"
REQUIRED_FIELDS = {"party", "clause_type", "responsibility", "page"}
MAX_TOKENS = 2048


def load_prompt() -> str:
    here = Path(__file__).parent
    return (here / "prompts" / "extraction_prompt.md").read_text(encoding="utf-8")


def rasterize(pdf_path: Path, outdir: Path, dpi: int) -> list[Path]:
    """Delegate to scripts/rasterize.sh so the shell command is documented in
    one place. Returns the sorted list of page image paths."""
    here = Path(__file__).parent
    script = here / "scripts" / "rasterize.sh"
    subprocess.check_call(
        ["bash", str(script), str(pdf_path), str(outdir), str(dpi)]
    )
    return sorted(outdir.glob("page-*.png"))


def encode_image(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": data},
    }


def call_anthropic(api_key: str, model: str, prompt: str,
                   image_path: Path, page_num: int) -> str:
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": prompt,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"This is page {page_num} of the document."},
                encode_image(image_path),
            ],
        }],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            return block.get("text") or ""
    return ""


def parse_and_validate(raw: str, page_num: int) -> list[dict]:
    """Parse the model's response into a list of clause objects. Raise
    ValueError with a specific message if anything is off."""
    text = (raw or "").strip()
    # The prompt says no code fences, but tolerate one so a stray ``` does
    # not break the run.
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"page {page_num}: JSON parse failed: {e}") from e
    if not isinstance(data, list):
        raise ValueError(
            f"page {page_num}: expected JSON array, got {type(data).__name__}"
        )
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            raise ValueError(f"page {page_num}: item {i} is not an object")
        missing = REQUIRED_FIELDS - set(obj.keys())
        if missing:
            raise ValueError(
                f"page {page_num}: item {i} missing fields: {sorted(missing)}"
            )
    return data


def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["page", "party", "clause_type", "responsibility"]
        )
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in writer.fieldnames})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", help="Input PDF path")
    parser.add_argument("csv_out", help="Output CSV path")
    parser.add_argument("--dpi", type=int, default=200,
                        help="Rasterization DPI (default 200)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Anthropic model (default {DEFAULT_MODEL})")
    args = parser.parse_args(argv)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 3

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"error: input PDF not found: {pdf_path}", file=sys.stderr)
        return 3

    prompt = load_prompt()
    all_rows: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            images = rasterize(pdf_path, Path(tmpdir), args.dpi)
        except subprocess.CalledProcessError as e:
            print(f"error: rasterize failed with exit {e.returncode}", file=sys.stderr)
            return 3
        if not images:
            print("error: no page images produced by pdftoppm", file=sys.stderr)
            return 3
        print(f"[extract] rasterized {len(images)} pages at {args.dpi} DPI",
              file=sys.stderr)

        for i, img in enumerate(images, 1):
            print(f"[extract] page {i} ...", file=sys.stderr, flush=True)
            try:
                raw = call_anthropic(api_key, args.model, prompt, img, i)
                rows = parse_and_validate(raw, i)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:500]
                print(f"error: page {i}: HTTP {e.code}: {detail}", file=sys.stderr)
                return 1
            except urllib.error.URLError as e:
                print(f"error: page {i}: could not reach API: {e.reason}",
                      file=sys.stderr)
                return 2
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            # Trust our page counter, not the model.
            for r in rows:
                r["page"] = i
            all_rows.extend(rows)

    write_csv(all_rows, Path(args.csv_out))
    print(
        f"[extract] wrote {len(all_rows)} clauses to {args.csv_out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
