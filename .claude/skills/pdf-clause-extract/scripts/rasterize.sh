#!/usr/bin/env bash
# Rasterize a PDF to per-page PNGs using pdftoppm.
#
# Usage: rasterize.sh <input.pdf> <output_dir> [dpi]
#
# Output files are written as <output_dir>/page-1.png, page-2.png, etc.
# The default DPI (200) is a compromise between OCR-quality and API cost;
# raise to 300 for dense small type, lower to 150 to save tokens.

set -euo pipefail

input="${1:?usage: rasterize.sh input.pdf output_dir [dpi]}"
outdir="${2:?usage: rasterize.sh input.pdf output_dir [dpi]}"
dpi="${3:-200}"

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "rasterize.sh: pdftoppm not found on PATH; install Poppler" >&2
  exit 3
fi

mkdir -p "$outdir"
pdftoppm -r "$dpi" -png "$input" "$outdir/page"
