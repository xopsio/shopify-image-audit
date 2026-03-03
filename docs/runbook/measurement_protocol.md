# Measurement protocol (v0.1)

Goal: repeatable Lighthouse-based measurements.

## Runs
- Run **mobile** and **desktop** separately.
- Do **3 runs** per device.
- Use the **median** result for reporting.

## Consistency
- Use the same URL for before/after.
- Don’t change theme/apps between before/after, except the intended image changes.
- Keep the same network and machine when comparing.

## Output
- Save raw Lighthouse JSON per run (into `fixtures/` or `artifacts/`).
- Produce a single `audit_result.json` matching the JSON schema.