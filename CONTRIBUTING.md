# Contributing

Welcome! This document covers everything you need to set up the project
locally, run the test suite, and ship a change. For governance and
domain ownership, see [`docs/governance.md`](docs/governance.md).

---

## 1. Setting up the dev environment

### 1.1 System dependencies (Linux)

The PDF renderer requires native libraries:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

On macOS these come pre-installed via Homebrew.

On Windows use the GTK3 runtime from MSYS2 (advanced; recommended only for
heavy local PDF work — CI covers Windows paths separately).

### 1.2 Python environment

```bash
git clone https://github.com/xopsio/shopify-image-audit.git
cd shopify-image-audit
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Verify the install:

```bash
audit version          # Should print the package version
pytest -q              # Should run all 695+ tests
ruff check src/ tests/ # Should report "All checks passed!"
mypy src/              # Should report "Success: no issues found"
```

---

## 2. Running tests

```bash
pytest -q                                    # full suite
pytest tests/test_history.py                  # one file
pytest tests/test_history.py::TestHistoryStore # one class
pytest tests/test_history.py::TestHistoryStore::test_record_creates_file  # one test
```

### 2.1 Updating snapshots

Snapshot tests live in `tests/test_snapshots.py` and a few others. To
update the golden files after an intentional change:

```bash
pytest tests/test_snapshots.py --snapshot-update
```

Commit the updated `tests/__snapshots__/*.ambr` file alongside your change.

### 2.2 Coverage

The CI run enforces `--cov-fail-under=90`. To see coverage locally:

```bash
pytest --cov=src --cov-report=term-missing
```

Lines marked `Missing` are uncovered statements.

### 2.3 Type checking

`mypy src/` is a CI gate (Sprint 10). The config lives in
`[tool.mypy]` in `pyproject.toml`; the goal is zero `# type: ignore`
comments. The normalized image dict is typed as `ImageDict`
(`core/image_signals.py`) — when touching the pipeline, keep dict
values inside that contract instead of widening to `dict[str, Any]`.

---

## 3. Adding a new CLI command

1. Add the command in `src/engine/cli.py` using the existing `@app.command()`
   pattern.
2. Decorate it with one of the error handlers from
   `src/engine/cli_helpers/_errors.py` (`@handle_json_errors`,
   `@handle_pipeline_errors`, `@handle_compare_errors`,
   `@handle_shopify_errors`). Don't write inline `try/except → rprint → Exit`.
3. Add tests in `tests/test_cli_coverage.py` (or a new file if the
   command is brand-new).
4. Update `docs/spec/cli_v0_1.md` with the new command's contract.

---

## 4. Adding a new HTML render function

1. Add the render function in `src/audit/report.py` (or
   `src/engine/history.py` for trend / diff HTML).
2. Make sure the output is deterministic (no `datetime.now()`, no
   random IDs) so it can be snapshot-tested.
3. Add a snapshot test in `tests/test_snapshots.py` (or
   `tests/test_history.py` for trend HTML).
4. Run `pytest --snapshot-update` to generate the golden file.

---

## 5. Branch + commit conventions

- Branch off `main` (e.g. `feat/my-feature`, `fix/issue-123`).
- One PR per ticket. Keep PRs focused.
- Use Conventional Commits in the commit subject:
  `FEAT: …`, `FIX: …`, `TEST: …`, `DOCS: …`, `REFACTOR: …`, `CHORE: …`.
- All PRs require:
  - `pytest -q` green
  - `ruff check src/ tests/` green
  - At least one new test (no untested code)
- See [`docs/governance.md`](docs/governance.md) for the full workflow.

---

## 5b. Environment variables (canonical reference)

Every env var the tool honors, in one place. Documented in detail at
the call sites; this table is the lookup.

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `WARNING` | Logger level (`DEBUG` / `INFO` / `WARNING` / `ERROR`). |
| `PAGESPEED_CACHE_TTL` | `3600` (1h) | PageSpeed response cache TTL in seconds. `0` disables. |
| `PAGESPEED_API_KEY` | (none) | Google Cloud API key for higher PageSpeed rate limits. Equivalent to passing `--api-key` on `measure` / `compare` / `schedule run-all`. |
| `XDG_DATA_HOME` | `~/.local/share` | Base directory for `schedules.json` + `history/` + `cache/`. |
| `SHOPIFY_ACCESS_TOKEN` | (none) | Admin API token for `audit shopify auth` / `inventory`. Equivalent to `--access-token`. |
| `SHOPIFY_IMAGE_AUDIT_CONFIG` | (none) | Override the config file location (default: `$XDG_CONFIG_HOME/shopify-image-audit/config.toml`). |
| `XDG_CONFIG_HOME` | `~/.config` | Base directory for `config.toml` (Sprint 11). |

Precedence: CLI flags > env var > config file > default. If a user passes
both `--api-key xxx` and `PAGESPEED_API_KEY=yyy`, the flag wins; the env
var wins over `[pagespeed] api_key` in `config.toml`.

### 5b.1 Configuration file

`~/.config/shopify-image-audit/config.toml` (or
`$XDG_CONFIG_HOME/shopify-image-audit/config.toml`) sets repeated
options. Example:

```toml
[defaults]
device = "mobile"        # run / baseline / schedule add
strategy = "mobile"      # measure / compare
parallel = 4             # shopify batch / schedule run-all (0 = unlimited)

[pagespeed]
api_key = "AIza..."      # equivalent to --api-key / $PAGESPEED_API_KEY
cache_ttl = 3600         # equivalent to $PAGESPEED_CACHE_TTL

[shopify]
access_token = "shpat_..."   # equivalent to --access-token

[history]
history_dir = "/srv/audit/history"   # overrides the XDG data dir

[report]
output = "report.html"   # default for `audit report -o`
brand_color = "#ff6b35"
brand_logo = "/etc/audit/logo.png"
```

Rules:

- A broken config (unparsable TOML, unknown section, invalid value)
  logs a warning and falls back to defaults — it never blocks a run.
- The file may contain secrets (`api_key`, `access_token`); keep it
  private: `chmod 600 ~/.config/shopify-image-audit/config.toml`.
- `no_cache` / `stop_on_error` / `pdf` are **not** configurable
  (boolean flags have no reliable unset form).

---

## 6. Observability (logging)

Operators can get structured debug output by setting `LOG_LEVEL=DEBUG`:

```bash
LOG_LEVEL=DEBUG audit run https://example.myshopify.com
```

Output looks like:

```
2026-07-30 15:00:00 [INFO] shopify_image_audit: run_audit start: path=...
2026-07-30 15:00:00 [DEBUG] shopify_image_audit: parse stage: 12 image(s) extracted
...
```

The logger is configured by `engine._logging.configure()`, called once
from `main()`. Six hooks emit structured INFO/DEBUG/WARN events:

| Module | What gets logged |
|--------|------------------|
| `audit_orchestrator.run_audit` | INFO at start/complete, DEBUG per pipeline stage |
| `engine.history._prune` | DEBUG when oldest entries are deleted |
| `pagespeed_api.get_metrics` | INFO at request, DEBUG at retry |
| `cli._run_lighthouse` | INFO per run, ERROR on `CalledProcessError` |
| `audit.report._parse_brand_color` | DEBUG when invalid input rejected |
| `audit.report._read_brand_logo` | DEBUG when missing / oversized / unsupported |
| `audit_orchestrator._sanitise_image` | DEBUG when role rewritten to "unknown" |

---

## 7. Release process

1. Bump `version` in `pyproject.toml`.
2. Add an entry to `CHANGELOG.md` under the new version heading.
3. Update test-count and version references in `README.md` /
   `docs/ROADMAP.md`.
4. Open a PR titled `CHORE: vX.Y.Z release prep`.
5. After CI is green, merge the PR.
6. Push the version tag:
   ```bash
   git checkout main
   git pull origin main
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
7. The release workflow builds and publishes to PyPI via trusted
   publishing. Verify the run at
   <https://github.com/xopsio/shopify-image-audit/actions>.

---

## 8. Getting help

- Issues: <https://github.com/xopsio/shopify-image-audit/issues>
- Governance: [`docs/governance.md`](docs/governance.md)
- Architecture: [`README.md`](README.md) § Architecture
- Specs: [`docs/spec/`](docs/spec/)

Thanks for contributing! 🚀