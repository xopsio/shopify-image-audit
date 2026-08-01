# Lighthouse CLI Integration

The `audit run <url>` command shells out to the **Lighthouse CLI** to
generate a fresh Lighthouse Performance report. The CLI is a Node
package — not a Python dependency — so it must be installed separately.

## Requirements

| Dependency | Minimum | Notes |
|---|---|---|
| Node.js | 18 (LTS) | Lighthouse 11+ drops Node 16 |
| npm | 9+ | or pnpm 8+ / yarn 4+ |
| Chrome | bundled | Lighthouse ships its own Chrome; no system install needed |

Verify your environment:

```bash
node --version    # >= v18
which lighthouse  # must print a path
lighthouse --version  # >= 11.0.0
```

## Installation

### Standard: global npm install (recommended)

```bash
npm i -g lighthouse
```

This places `lighthouse` on `PATH` and is the path the tool resolves
automatically.

### Alternative: per-project install

```bash
npm install --save-dev lighthouse
```

Then point the tool at the local binary:

```bash
audit run https://your-store.myshopify.com \
  --lighthouse-bin ./node_modules/.bin/lighthouse
```

### Override via environment variable

For CI pipelines where editing `$PATH` is awkward:

```bash
export LIGHTHOUSE_BIN=/opt/lighthouse/node_modules/.bin/lighthouse
audit run https://your-store.myshopify.com
```

## Resolution order

The tool resolves the Lighthouse binary in this order (first hit wins):

1. `--lighthouse-bin PATH` flag
2. `$LIGHTHOUSE_BIN` environment variable
3. `shutil.which("lighthouse")` — i.e. global PATH lookup

If none of these resolve to an existing file, the tool exits with
code **10** (`Backend / Lighthouse / API failure`) and prints a help
message listing every option above.

## Bypass: use a pre-existing Lighthouse report

If you cannot install Lighthouse (e.g. locked-down CI, missing sudo,
or you already have a report), pass `--lhr` and the tool skips the
binary entirely:

```bash
audit run https://your-store.myshopify.com \
  --lhr ./existing-lighthouse.json
```

The file must be a valid Lighthouse JSON (audit_result.json / lhr.json
shape). The tool does not validate the structure beyond what
`run_audit` requires — if parsing fails, error code **10** is returned.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `lighthouse: not found` in error | PATH doesn't include the install dir | Use `--lighthouse-bin` or `LIGHTHOUSE_BIN` |
| `Lighthouse failed (run 1): ...` | Chrome cannot launch (sandbox, missing deps) | Run `lighthouse --help` directly to see Chrome errors |
| Run hangs forever | Network timeout to the target | The tool enforces a **10-minute per-run timeout**; if you see this, file an issue |
| `Lighthouse timed out after 600s` | Page is genuinely slow under headless Chrome | Increase `--runs 1` or accept the failure |
| Permission denied on the binary | Lighthouse installed as another user | Re-install or use `--lighthouse-bin /full/path/to/lh` |

## CI recipes

### GitHub Actions

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: '20'
- run: npm i -g lighthouse
- run: audit run https://your-store.myshopify.com
```

### Docker (no global npm)

```dockerfile
RUN npm install -g lighthouse
ENV PATH="/usr/local/bin:${PATH}"
```

### Pinned version (reproducible)

```bash
npm i -g lighthouse@12
```

## Related

- `audit measure` — uses the PageSpeed Insights REST API; no Lighthouse
  install required (only needs `$PAGESPEED_API_KEY` for higher rate limits).
- `audit baseline --lhr <file>` — accepts an existing Lighthouse JSON,
  same bypass as `run --lhr`.
