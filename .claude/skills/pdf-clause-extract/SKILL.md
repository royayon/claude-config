---
name: pdf-clause-extract
description: "Extracts clauses from a scanned or badly-encoded PDF (e.g. a commercial lease) into structured JSON, then validates and writes a CSV. Rasterizes pages with pdftoppm, sends page images to the Claude API against a small clause schema (party, clause_type, responsibility, page). Use when direct text extraction from a PDF fails or produces garbage."
---

# pdf-clause-extract

For PDFs where copy-paste text extraction produces garbage: scanned images, PDFs with broken font encodings, PDFs where each character is its own custom glyph. The workflow rasterizes each page to a PNG, sends the image to the Claude API with a versioned extraction prompt, validates the JSON, and writes a CSV of clauses.

## When to invoke

- The user asks to pull clauses (or any structured content) out of a PDF that direct text extraction failed on.
- The PDF looks like a scan (embedded images, no selectable text) or produces gibberish when text-extracted.
- The user references contracts, leases, agreements, or invoices in image-form.

For clean text-PDFs, use direct extraction (e.g., `pdftotext` or `pypdf`); this skill is overkill for those.

## Design decisions worth noticing

- **Rasterize first.** `pdftoppm` produces one PNG per page. Direct text extraction is unreliable on scans and on PDFs with custom font encodings; page images sidestep both problems by handing the model exactly what a human would see.
- **Prompt in a versioned file.** `prompts/extraction_prompt.md` is separate from `extract.py` on purpose: prompt evaluation and iteration is easier when the prompt has its own change history, and swapping a new prompt version does not require touching the driver.
- **Model is not trusted with the page number.** The driver overwrites the `page` field on every returned object with the page number the caller sent. The model can drift on this; the caller cannot.
- **Validated JSON only.** Every returned array is JSON-parsed and every object is checked for the four required fields (`party`, `clause_type`, `responsibility`, `page`). A parse failure or missing field fails the run.

## Schema

Each clause row is:

| Field | Type | Description |
|---|---|---|
| `page` | int | 1-indexed page number |
| `party` | str | Party the clause applies to: "Landlord", "Tenant", "Guarantor", "Both", etc. |
| `clause_type` | str | One of a small vocabulary (see prompt); a new snake_case label is allowed for unusual clauses |
| `responsibility` | str | One sentence describing the specific obligation |

## Prerequisites

- **`pdftoppm`** on PATH. Ships with Poppler:
  - macOS: `brew install poppler`
  - Debian / Ubuntu: `apt install poppler-utils`
  - Windows: install Poppler from a distribution such as `conda install -c conda-forge poppler` or the release binary from the Poppler-Windows GitHub project, then add its `bin/` to PATH.
- **`ANTHROPIC_API_KEY`** in env. Copy `.env.example` to `.env` and set it there.
- **Python 3.9+** for the driver (`extract.py`). Stdlib only, no `pip install` needed.
- **`reportlab==4.4.4`** if you want to regenerate the synthetic sample PDF at `examples/sample_lease.pdf`. Not needed to run extraction.

## Usage

```
export ANTHROPIC_API_KEY=sk-ant-...
python .claude/skills/pdf-clause-extract/extract.py \
  examples/sample_lease.pdf \
  out/lease_clauses.csv
```

Optional flags:
- `--dpi 200` (default): rasterization DPI. 300 for smaller text; 150 to save API tokens.
- `--model claude-sonnet-4-6` (default): the model to call.

The CSV columns are `page, party, clause_type, responsibility` in that order.

## Prompt iteration

If extractions look off, edit `prompts/extraction_prompt.md` and rerun. The prompt is intentionally small (one screen) and describes: the schema, the vocabulary of `clause_type`, the "return `[]` on empty pages" rule, and the "do not invent" rule. Version prompts by keeping the previous versions in `prompts/` as `extraction_prompt_v1.md`, `extraction_prompt_v2.md`, etc., and pointing the current version at `extraction_prompt.md` (symlink or copy) so `extract.py` doesn't need to change.

## End-to-end run

The synthetic 2-page `examples/sample_lease.pdf` is committed so a reviewer can exercise the flow in one command:

```
export ANTHROPIC_API_KEY=sk-ant-...
python .claude/skills/pdf-clause-extract/extract.py \
  examples/sample_lease.pdf \
  /tmp/sample_lease.csv
head -20 /tmp/sample_lease.csv
```

The synthetic lease invents parties (Northwood Real Estate Holdings LLC, Sunbird Bakery Cafe Inc., Acme Guarantee Corp.) and a plausible clause set (rent, term, use, utilities, maintenance, insurance, indemnity, default, guaranty). Regenerate any time from `examples/generate_sample_lease.py`.
