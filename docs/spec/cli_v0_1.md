# CLI v0.1 spec

## Commands

### `audit run <url>`
Runs Lighthouse and writes raw results.
- Flags:
  - `--device mobile|desktop` (default `mobile`)
  - `--runs 3` (default 3)
  - `--out-dir <path>` (default `artifacts/`)
  - `--lhr <path>` (use an existing Lighthouse JSON instead of running live)
- Exit codes:
  - 0 success
  - 2 invalid args (bad URL scheme, bad device, unsafe path, invalid JSON)
  - 10 lighthouse failure

### `audit extract <lighthouse.json>`
Extracts image + LCP-related features into an intermediate JSON.

### `audit score <audit_input.json>`
Assigns:
- `role` (hero/above_fold/product_primary/product_secondary/decorative/unknown)
- `score` 0–100
- recommendations

### `audit report <audit_result.json>`
Renders an HTML report.
- Flags:
  - `-o, --output <path>` (default `report.html`)

### `audit measure <url>` *(Sprint 2, JB-002)*
Fetches live performance metrics from the Google PageSpeed Insights API.
- Flags:
  - `--strategy mobile|desktop` (default `mobile`)
  - `--api-key <key>` (optional)
  - `-o, --output <path>` (default: print JSON to stdout)
- Exit codes:
  - 0 success
  - 2 invalid args (bad URL, bad strategy, unsafe output path)
  - 10 API failure / rate limit

### `audit baseline <lhr.json>` *(Sprint 2, #18)*
Runs the audit pipeline on a Lighthouse JSON / fixture report and stores the
result as a reusable baseline (`audit_result.json`).
- Flags:
  - `--save <path>` (required) — where to write the baseline
  - `--url <url>` (optional) — override the store URL in the baseline meta
  - `--device mobile|desktop` (default `mobile`)
- Exit codes: 0 success, 2 invalid args (missing file, bad device, unsafe path), 10 pipeline failure
- Output path safety: `--save` is run through the same path-validation as
  `run --out-dir` (no absolute paths, no `..`, must stay within cwd → exit 2).

### `audit compare <baseline.json> <current>` *(Sprint 2, #18/#20 + Sprint 3 live URL)*
Compares a baseline audit against a current audit and reports before/after deltas.
- Each input may be:
  - a saved `audit_result.json` (from `audit baseline`)
  - a raw Lighthouse/fixture report (run through the audit pipeline)
  - **a live URL** (`http://` / `https://`) — fetched via PageSpeed Insights API
- Flags:
  - `-o, --output <path>` — write an HTML before/after report (default: stdout JSON)
  - `--json <path>` — also write the comparison JSON
  - `--strategy mobile|desktop` — PageSpeed strategy when `<current>` is a URL
  - `--api-key <key>` — optional Google Cloud API key for higher rate limits
- Output: `ComparisonResult` (vitals deltas + image aggregate deltas + ROI
  estimate). Units mirror `Vitals`: ms for LCP/INP/TTFB, unitless for CLS.
- Exit codes: 0 success, 2 invalid args (missing file, bad URL, unsafe path),
  10 backend failure (PageSpeed API error after retries).
- Output path safety: `-o`/`--json` are run through path-validation (exit 2).

## Required final output
`audit_result.json` MUST validate against `schemas/audit_result.schema.json`.
Comparison outputs (`ComparisonResult`) are a separate data contract, not part
of `audit_result.schema.json`.

## Exit code conventions
- `0` — success
- `2` — invalid arguments (bad URL, missing file, invalid JSON, unsafe path)
- `10` — backend/Lighthouse/API failure
