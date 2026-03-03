# CLI v0.1 spec

## Commands

### `audit run <url>`
Runs Lighthouse and writes raw results.
- Flags:
  - `--device mobile|desktop` (required)
  - `--runs 3` (default 3)
  - `--out-dir <path>` (default `artifacts/`)
- Exit codes:
  - 0 success
  - 2 invalid args
  - 10 lighthouse failure

### `audit extract <lighthouse.json>`
Extracts image + LCP-related features into an intermediate JSON.

### `audit score <audit_input.json>`
Assigns:
- `role` (hero/above_fold/product_primary/product_secondary/decorative)
- `score` 0–100
- recommendations

### `audit report <audit_result.json>`
Renders an HTML report.

## Required final output
`audit_result.json` MUST validate against `schemas/audit_result.schema.json`.