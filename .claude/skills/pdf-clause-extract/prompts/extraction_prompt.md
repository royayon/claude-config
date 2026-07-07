# pdf-clause-extract prompt (v1)

You are reviewing rasterized page images of a commercial lease or similar contract. For each clause you can identify on the page, produce one JSON object with these four fields.

## Schema

- `party` (string): the party the clause primarily applies to. Use the role name as written in the document ("Landlord", "Tenant", "Guarantor", "Seller", "Buyer", etc.). If a clause imposes obligations on more than one party, use "Both".
- `clause_type` (string): a short snake_case label. Prefer these when they fit: `rent`, `term`, `use`, `maintenance`, `insurance`, `indemnity`, `default`, `termination`, `notices`, `subletting`, `alterations`, `security_deposit`, `taxes`, `utilities`, `guaranty`, `assignment`. Coin a new snake_case label only if none of the above fit.
- `responsibility` (string): one sentence describing the specific action or obligation. Preserve numeric values (dollar amounts, days, percentages) verbatim. Quote the original text when the exact wording is legally material.
- `page` (integer): the page number given in the user message. Return the number you were told; do not guess.

## Output format

Return ONLY a JSON array of objects. No prose. No code fences. No trailing commas. If the page contains no clauses (a title page, a signature block only, a table of contents), return `[]`.

Example (for illustration; do not copy):

```
[
  {"party": "Tenant", "clause_type": "rent", "responsibility": "Pay $8,500 monthly base rent on or before the first day of each month.", "page": 1},
  {"party": "Landlord", "clause_type": "maintenance", "responsibility": "Maintain the roof, exterior walls, foundation, and structural components.", "page": 1}
]
```

## Rules

1. Do not invent parties, dollar amounts, or terms that are not present on the page.
2. Do not summarize the entire document. Extract clause-by-clause: one JSON object per obligation.
3. If a single paragraph contains obligations for different parties, emit one object per party.
4. If the same paragraph imposes multiple distinct obligations on the same party (rent AND late fee, for instance), emit one object per obligation.
5. The output MUST be valid JSON.
