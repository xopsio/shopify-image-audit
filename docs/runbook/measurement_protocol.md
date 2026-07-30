# Measurement protocol

Goal: repeatable Lighthouse-based measurements for image-audit reports.

## Runs

- Run **mobile** and **desktop** separately (`--device mobile|desktop`).
- The default `--runs` is 3 — but be aware that the current implementation
  uses **the last successful run's results** as the canonical `AuditResult`,
  not the median across runs. This is a known limitation; if you need true
  median aggregation, run each pass manually and feed the median LHR into
  `audit baseline <lhr.json>`.
- Each run writes `lhr_run1.json`, `lhr_run2.json`, `lhr_run3.json` into
  `--out-dir` (default `artifacts/`).

## Consistency

- Use the **same URL** for before/after.
- Don't change theme/apps between before/after, except the intended image
  changes.
- Keep the same network and machine when comparing.
- For PageSpeed Insights API (`audit measure`, `audit compare --live`):
  the response is cached locally for the duration of
  `PAGESPEED_CACHE_TTL` (default 3600s) so repeated invocations within
  the TTL don't re-hit the network.

## Output

- Save raw Lighthouse JSON per run (into `fixtures/` or `artifacts/`).
- Produce a single `audit_result.json` matching the JSON schema
  (`schemas/audit_result.schema.json`).
- The HTML report footer shows the actual tool version (read from
  `pyproject.toml` at runtime).

## Caveats

- **No median aggregation across runs.** Each Lighthouse run is a
  single sample; the current pipeline picks the last successful run.
- **PageSpeed rate limits.** Free tier allows ~20 requests/minute
  without an API key. Use `--api-key` for higher limits, or rely on the
  on-disk cache (`PAGESPEED_CACHE_TTL`).
- **WeasyPrint native deps.** PDF export requires `libpango`,
  `libcairo`, `libgdk-pixbuf` on the host. See
  [`CONTRIBUTING.md`](../../CONTRIBUTING.md) §1.1 for installation
  instructions.