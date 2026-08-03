# Changelog

All notable changes to **shopify-image-audit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.17.0] - 2026-08-01

### Added (Sprint 25)
- **Authenticated Lighthouse for password-protected Shopify
  storefronts**: new `--storefront-password <pwd>` option (and
  `$SHOPIFY_STOREFRONT_PASSWORD` env var) on `audit run`. The CLI
  POSTs the storefront `/password` form once, captures the
  `_shopify_essential` cookie, and threads it into Lighthouse via
  `--extra-headers` — closing the v0.16.4 limitation that
  prevented auditing any non-public store.
- New `src/integrations/storefront_auth.py` module: typed
  exceptions (`StorefrontWrongPasswordError`,
  `StorefrontCaptchaError`, `StorefrontMissingCookieError`,
  `StorefrontUnexpectedResponseError`, `StorefrontNetworkError`)
  and a `StorefrontSession` dataclass carrying the cookie header.
- New `tests/test_storefront_auth.py` (10 tests): success, wrong
  password, hCaptcha detection, missing cookie, unexpected status,
  network error, `--extra-headers` threading, end-to-end CLI
  integration.

### Limitations
- Stores with hCaptcha on the password form are not supported
  (the CLI prints a clear error and exits 2).
- Only the storefront password flow is implemented — admin login,
  customer login, multi-factor remain out of scope.
- The session is **not** persisted; each `audit run` re-authenticates.

### Stats
- 825 tests pass (up from 815; +10 in `test_storefront_auth.py`),
  22 snapshots unchanged.

---

## [0.16.4] - 2026-08-01

### Fixed (Sprint 24)
- **Audit-truth on empty / off-target pages**: when the audited
  page is empty, behind a Shopify storefront password, an auth
  wall, a 404 fallback, or otherwise has zero extractable images,
  v0.16.3 silently produced "All images look well optimised".
  v0.16.4 replaces that with a clear "No images were extracted"
  message naming the likely causes.
- **Redirect detection on the Lighthouse result**: `_run_lighthouse`
  now reads `finalUrl` / `finalDisplayedUrl` and refuses to claim
  success when the page was redirected off-target (exit 10 with a
  clear error). Catches the Shopify-password case at the
  source — no misleading `audit_result.json` is written.

### Tests (Sprint 24)
- New `tests/test_audit_truth.py` (12 tests): empty-images
  summary, redirect detection across no-redirect / password /
  same-host-404 / cross-host / corrupt-LHR / unparseable-URL
  cases, and an end-to-end CLI integration test.
- 812 tests pass (up from 800; +12 in `test_audit_truth.py`),
  22 snapshots unchanged.

### Docs (Sprint 24)
- `docs/integrations/LIGHTHOUSE.md` gains a "Limitations" section
  documenting the no-auth constraint and the manual `--lhr`
  workaround.

---

## [0.16.3] - 2026-08-01

### Fixed (Sprint 23)
- **`audit run --device mobile` regression**: Lighthouse CLI rejected
  `--preset=mobile` and aborted before any network request. Mobile
  now builds the cmd without `--preset` (Lighthouse default is mobile)
  and without the redundant `--emulated-form-factor=mobile`. Desktop
  still passes `--preset=desktop`. v0.16.2 is broken for mobile runs
  on Lighthouse 12+/13+.

### Tests (Sprint 23)
- `TestRunLighthouseCmdShape` pins the exact `cmd` list passed to
  `subprocess.run` for mobile, desktop, and multi-run paths —
  prevents future `--preset=mobile` regressions
- 3 new tests; 800 total

---

## [0.16.2] - 2026-08-01

### Added (Sprint 22)
- `audit shopify login --stores-file stores.json` authorises every
  store in the file in one run — each store gets its own browser
  flow with the standard 60-second callback timeout — TD-1
- Per-store failures (denied / timeout / exchange error) do not
  abort the run: a summary line reports `N authorised, M failed`
  and the command exits with code 2 if any store failed — TD-1
- `_login_one_store` helper extracted from `_shopify_login`; the
  single-store path is unchanged (exit 2 on failure, "next steps"
  hint on success) — TD-1
- First CLI-level test coverage for `audit shopify login`
  (`tests/test_shopify_login_cli.py`): 12 tests with a fake
  callback server and stubbed token exchange — TD-3

### Changed (Sprint 22)
- `--stores-file` help text now covers both `batch` and `login` —
  TD-2
- `docs/integrations/SHOPIFY_OAUTH.md` gains a "Batch login"
  section; the multi-store item is struck through in the deferred
  list; `SHOPIFY_ADMIN.md` documents the one-shot login step —
  TD-4

### Stats
- 797 tests pass (up from 785; +12 across `test_shopify_login_cli.py`),
  22 snapshots unchanged

---

## [0.16.1] - 2026-08-01

### Added (Sprint 21)
- `audit shopify batch --stores-file` now reads access tokens
  automatically from `tokens.json` when a store entry has no
  `access_token` — log each store in once with
  `audit shopify login <store>` and batch audits work with a
  credential-free `stores-file` — TD-1
- Explicit `access_token` still wins over the persisted token
  (backwards compatible with existing `stores.json` files) — TD-1

### Changed (Sprint 21)
- `StoreConfig.access_token` is now optional (`str | None`)
- `--stores-file` help text documents the optional token — TD-2
- `docs/integrations/SHOPIFY_ADMIN.md` gains a batch-audit section
  with a credential-free stores-file example; `SHOPIFY_OAUTH.md`
  deferred list updated — TD-4

---

## [0.16.0] - 2026-08-01

### Added (Sprint 20)
- `tokens.json` is now **encrypted at rest** with Fernet
  (AES-128-CBC + HMAC). The key lives in the platform's system
  keyring (macOS Keychain / Windows Credential Manager / Linux
  Secret Service), so desktop users see no prompts — TD-1..3
- New `engine/_crypto.py` module: `get_or_create_fernet_key`,
  `encrypt_mapping`, `decrypt_mapping`, `derive_key_from_passphrase`
  (scrypt fallback for headless Linux) — TD-1
- `$SHOPIFY_AUDIT_TOKENS_DISABLED=1` opt-out for CI environments
  without D-Bus / Secret Service — TD-3
- `handle_shopify_errors` decorator now distinguishes
  token-decryption failures ("Token decryption failed: run
  `audit shopify login <store>` to refresh") from generic API
  errors — TD-4

### Changed (Sprint 20)
- New runtime dependencies: `cryptography>=42,<46`,
  `keyring>=24,<26`, `secretstorage>=3.3` (Linux only) — TD-2
- `docs/integrations/SHOPIFY_OAUTH.md` Token storage section
  documents the on-disk envelope and disable flag — TD-6

### Security
- `grep tokens.json` no longer reveals access tokens
- `chmod 0600` preserved (POSIX)
- Access tokens never logged (unchanged since Sprint 19)

### Stats
- 780 tests pass (up from 752; +28 across `test_crypto` and
  `test_tokens` encryption tests)
- `mypy src/` (strict): Success, 34 source files, zero ignores
- Ruff check + format clean
- 84 PRs merged

---

## [0.15.0] - 2026-08-01

### Added (Sprint 19)
- `audit shopify login <store>` — automates the custom-app token flow
  that previously required 10 manual steps in the Shopify admin. Opens
  the user's browser to the official OAuth authorize URL, waits on a
  local HTTP server for the redirect, exchanges the code for an
  access token, and persists the token in `tokens.json` (mode 0600).
  Closes the long-deferred "OAuth flow for Shopify Admin" roadmap
  item — TD-4
- New `integrations/shopify_oauth.py` — `build_authorize_url`,
  `exchange_code_for_token`, `generate_state` (`secrets.token_urlsafe(32)`),
  and `validate_state` (`secrets.compare_digest` for constant-time CSRF
  check) — TD-1
- New `integrations/oauth_callback_server.py` — embedded
  `ThreadingHTTPServer` bound to `127.0.0.1` (port auto-selected in
  `18765-18774`) with 60-second timeout, idempotent stop, and
  context-manager support — TD-2
- New `engine/tokens.py` — `TokensStore` (`{shop_domain: access_token}`
  map, JSON-on-disk with `chmod 0o600`, Windows non-fatal). Distinct
  from `ScheduleStore` so schedule metadata and credentials can be
  shared independently — TD-3
- `ShopifyConfig` gains `client_id`, `client_secret`, `redirect_uri`,
  `scopes` fields (config / env / flag precedence preserved) — TD-3
- `audit shopify auth <store>` and `audit shopify inventory <store>`
  automatically read the token from `TokensStore` when no
  `--access-token` is supplied — TD-4
- New `docs/integrations/SHOPIFY_OAUTH.md` (~150 lines) covers setup,
  security properties, headless-mode, and troubleshooting — TD-6

### Security
- CSRF state uses `secrets.compare_digest` (constant time)
- Callback server binds to `127.0.0.1` only (no external interface)
- Access tokens are never logged
- `tokens.json` is created with mode `0600` on POSIX (Windows non-fatal)
- Token **encryption** is explicitly out of scope for v0.15.0 and
  tracked as a deferred roadmap item

### Stats
- 752 tests pass (up from 726; +26 across `test_shopify_oauth`,
  `test_oauth_callback_server`, `test_tokens`)
- `mypy src/` (strict): Success, 33 source files, zero ignores
- Ruff check + format clean
- 83 PRs merged

---

## [0.14.0] - 2026-08-01

### Added (Sprint 18)
- TypedDict contracts for every Shopify Admin API response this module
  consumes — `ShopInfo` / `ShopEnvelope` (`/shop.json`),
  `ProductSummary` / `ProductListEnvelope` (`/products.json`),
  `ThemeSummary` / `ThemeListEnvelope` (`/themes.json`),
  `ThemeAssetSummary` / `ThemeAssetListEnvelope`
  (`/themes/{id}/assets.json`). Slim client-side output shapes
  (`ShopSummary`, `ProductEntry`, `ThemeAssetEntry`) are typed
  separately. All `total=False` so the existing `.get(...)`-based
  reads and partial-mock tests keep working.

### Changed (Sprint 18)
- `get_shop_info() -> ShopSummary` (was `dict[str, str]`)
- `get_products() -> list[ProductEntry]` (was `list[dict[str, Any]]`)
- `get_theme_assets() -> list[ThemeAssetEntry]` (was
  `list[dict[str, str]]`)
- `docs/integrations/SHOPIFY_ADMIN.md` documents the new contracts
  section so contributors see which fields are consumed.

### Stats
- 726 tests pass (up from 721; +5 `TestShopifyTypedDicts` cases)
- `mypy src/` (strict): Success, 30 files, zero ignores
- Ruff check + format clean
- 82 PRs merged

---

## [0.13.0] - 2026-08-01

### Added (Sprint 17)
- `audit shopify batch` and `audit schedule run-all` now show a live
  Rich Progress bar (`SpinnerColumn` + `TextColumn` + `BarColumn` +
  `MofNCompleteColumn` + `TimeElapsedColumn`) while the run is
  in flight — TD-3
- New `on_done` keyword callback parameter on `run_parallel` (and
  forwarded by `run_batch` and `run_all_schedules`) lets callers
  observe each completed item without re-implementing the loop —
  callback exceptions are silently swallowed so a buggy handler
  never breaks the run — TD-1, TD-2

### Stats
- 721 tests pass (up from 715; +6 callback tests)
- `mypy src/` (strict): Success, 30 files, zero ignores
- Ruff check + format clean
- 81 PRs merged

---

## [0.12.0] - 2026-08-01

### Added (Sprint 16)
- `--lighthouse-bin PATH` flag on `audit run` (overrides everything
  else when the binary is not on `PATH`) — TD-1
- `$LIGHTHOUSE_BIN` env var as second-tier override (via Typer
  `envvar=` binding) — TD-1
- 10-minute per-run subprocess timeout (`_LIGHTHOUSE_TIMEOUT_SECONDS`)
  prevents Lighthouse from hanging the audit indefinitely on stuck
  headless Chrome — TD-1
- Multi-line error message when no Lighthouse binary is found: lists
  every resolution path plus the `--lhr <file>` bypass — TD-1
- New `docs/integrations/LIGHTHOUSE.md` covers requirements, install
  options, resolution order, bypass, troubleshooting matrix, and CI
  recipes (GitHub Actions / Docker / pinned versions) — TD-3

### Fixed (Sprint 16)
- `_run_lighthouse` was unbounded — a stuck Lighthouse process now
  raises `typer.Exit(10)` via the new `subprocess.TimeoutExpired`
  handler — TD-1

### Stats
- 715 tests pass (up from 705; +10 Lighthouse tests; the
  `_run_lighthouse` 0/6 testing gap is now 6/6 covered)
- `mypy src/` (strict): Success, 30 files, zero ignores
- Ruff check + format clean
- 80 PRs merged

---

## [0.11.0] - 2026-08-01

### Added (Sprint 15)
- `LighthouseJson` + `AuditEntry` + `Categories` + `PerformanceCategory`
  TypedDict hierarchy documents the shape of every Lighthouse API
  response the runtime reads (`total=False` so partial mocks still
  validate) — TD-1
- `CachedPageSpeedResponse` TypedDict wraps the outer envelope (success
  → `lighthouseResult`; API error → `error`) — TD-1
- `CachedEntry` TypedDict in `ResponseCache` (`timestamp` + `data`) —
  TD-2

### Changed (Sprint 15)
- `PageSpeedAPIClient._parse_response` now takes `CachedPageSpeedResponse`
  (was `dict[str, Any]`); `fetch_lighthouse_json` returns
  `LighthouseJson` (was `dict[str, Any]`) — TD-1
- `run_audit()` types the parsed LHR as `LighthouseJson` via a
  structural cast — TD-3
- `_cache.py` carries a `TYPE_CHECKING` import of `CachedPageSpeedResponse`
  for documentation; the runtime `data` field stays `dict[str, Any]` to
  avoid a circular import — TD-2

### Stats
- 705 tests pass (up from 698; +7 typeddict smoke tests)
- `mypy src/` (strict): Success, 30 files, zero ignores
- Ruff check + format clean
- 79 PRs merged

---

## [0.10.1] - 2026-08-01

### Changed (Sprint 14)
- `ImageDelta.before` / `.after` tightened from `dict[str, Any] | None`
  to `ImageItem | None` — every image reaching `_match_images` is
  already a validated `ImageItem` (audit confirmed: 12 payload keys,
  all ImageItem fields). Closes the Sprint 13 strict-mypy follow-up —
  TD-1
- `core.baseline_manager.py` drops `typing.cast` (4 sites) and
  `typing.Any` (no longer used); `ImageItem.model_validate` replaces
  the `cast(dict[str, Any], img)` pattern — TD-2

### Fixed (Sprint 14)
- 6 test fixtures in `test_baseline_manager.py` gained the two missing
  ImageItem-required fields (`role`, `score`). The minimal dicts
  previously violated the new constraint — TD-3

### Stats
- 698 tests pass (up from 695; +3 `TestImageDelta` cases)
- `mypy src/` (strict): Success, 30 files, zero ignores
- Ruff check + format clean
- 78 PRs merged

---

## [0.10.0] - 2026-08-01

### Added (Sprint 13)
- `[tool.mypy]` promoted to `strict = true` — every function typed,
  no implicit `Optional`, no untyped calls. CI gate strengthened —
  TD-1..5
- `ParamSpec` + `TypeVar` pattern in `engine/cli_helpers/_errors.py`
  preserves the wrapped function's signature through all four
  error-handling decorators (`handle_json_errors`,
  `handle_pipeline_errors`, `handle_compare_errors`,
  `handle_shopify_errors`) — TD-1

### Changed (Sprint 13)
- All `dict` / `list` / `Callable` annotations carry full generic
  arguments (`dict[str, Any]`, `list[Any]`,
  `Callable[[Callable[P, R]], Callable[P, R]]`) — TD-1..4

### Stats
- 695 tests pass (unchanged; pure hardening sprint)
- `mypy src/` (now `strict`): Success, 30 files, **zero** ignore comments
- Ruff check + format clean
- 77 PRs merged

---

## [0.9.1] - 2026-08-01

### Changed (Sprint 12)
- Repository formatted with `ruff format` (53 files reformatted). The
  drift accumulated during Sprint 10's mypy-gate work — every file now
  conforms to one canonical style — TD-1
- CI now runs `ruff format --check` after `ruff check` so format drift
  can't recur — TD-2

### Fixed (Sprint 12)
- Dependency refresh via 4 Dependabot PRs (all merged): `rich`
  constraint widened to `>=13.7,<16`, GitHub Actions versions bumped
  (`download-artifact 4→8`, `setup-python 5→7`,
  `attest-build-provenance 2→4`) — TD-3

### Stats
- 695 tests pass (unchanged; pure hygiene sprint)
- `ruff format --check`: 61 files already formatted (no drift)
- 76 PRs merged

---

## [0.9.0] - 2026-08-01

### Added (Sprint 11)
- User-side TOML config: `$XDG_CONFIG_HOME/shopify-image-audit/
  config.toml` with 13 keys / 5 sections (`[defaults]`, `[pagespeed]`,
  `[shopify]`, `[history]`, `[report]`) — TD-1+TD-2
- Precedence chain is **CLI flag > env var > config > default**,
  verified by tests at every layer — TD-1+TD-2
- `SHOPIFY_IMAGE_AUDIT_CONFIG` env var overrides the config file
  location — TD-1
- A broken config (unparsable TOML, unknown section, invalid value)
  warns and falls back to defaults — it never blocks a run — TD-1

### Notes
- `no_cache` / `stop_on_error` / `pdf` are deliberately NOT
  configurable: Typer boolean flags have no reliable "unset" form, so a
  config value could never be overridden back off from the CLI — TD-2

### Stats
- 695 tests pass (up from 672; +23 config tests)
- `mypy src/`: Success, 30 files, zero ignore comments
- Ruff clean
- 72 PRs merged

---

## [0.8.0] - 2026-08-01

### Added (Sprint 10)
- Mypy is a CI gate (`mypy src/` in CI, `[tool.mypy]` config) with the
  goal of zero `type: ignore` comments — TD-1
- `ImageDict` TypedDict (`core/image_signals.py`): the shared, typed
  contract for the normalized image dict across parser, extractor,
  rankers, orchestrator, baseline manager and report renderer — TD-1
- CycloneDX SBOM generated in the release pipeline and uploaded as a
  standalone release artifact (`sbom/sbom.cyclonedx.json`) — TD-2

### Fixed (Sprint 10)
- `run_parallel` was typed `Callable[[T], T]` but callers map
  item→result of different types; now correctly generic over two
  type variables (surfaced by mypy) — TD-1
- INP/FMP absent-vs-zero mapping in the PageSpeed client expressed as
  `float | None` instead of assigning `None` into a `float` — TD-1
- Dead `_CACHE_SUBDIR` constant removed; 4 unused `type: ignore`
  comments deleted — TD-1

### Stats
- 672 tests pass (unchanged; pure hardening sprint)
- `mypy src/`: Success, 29 files, zero ignore comments
- Ruff clean
- 65 PRs merged

---

## [0.7.1] - 2026-07-31

### Fixed (Sprint 9)
- JSON Schema contract now ships **inside the wheel** (was sdist-only via
  `MANIFEST.in`): schema moved to `src/audit/schemas/`, shipped via
  `[tool.setuptools.package-data]`, read via `importlib.resources` —
  TD-2
- `schedules.json` (holds Shopify access tokens) is written with
  `0600` permissions on POSIX — TD-3
- PageSpeed API key never leaks into error messages: requests
  connection errors embed the full request URL (`?key=...`), which is
  now redacted before the exception surfaces — TD-3

### Added (Sprint 9)
- `PAGESPEED_API_KEY` env var as fallback for all three `--api-key`
  flags (`measure`, `compare`, `schedule run-all`). Precedence:
  CLI flag > env var — TD-3
- `.github/ISSUE_TEMPLATE/` — bug report + feature request forms — TD-4
- Doc hygiene: test-count/coverage-gate drift fixed, CONTRIBUTING
  "Configuration" section (canonical env-var reference), tutorial
  phantom-flag fix, CLI spec additions — TD-1

### Stats
- 672 tests pass (up from 665)
- Ruff clean
- Schema reachable from an installed wheel via `importlib.resources`
- 64 PRs merged

---

## [0.7.0] - 2026-07-31

### Added (Sprint 8)
- "Did you mean: X?" suggestions on every CLI typo site (`--device`,
  `--strategy`, `--ranker`, shopify/history/schedule subcommands) via
  `difflib.get_close_matches` — TD-1
- `audit schedule run-all --parallel <N>` (deferred from Sprint 7; now
  trivial thanks to the shared `run_parallel` helper) — TD-3
- Shared `src/engine/_parallel.py::run_parallel(items, fn, *, parallel,
  stop_on_error, cancelled_factory)` is now the single concurrency
  primitive for `run_batch` and `run_all_schedules` — TD-3
- `tests/conftest.py` + `tests/__init__.py`: single source of truth for
  shared `REPO_ROOT`, `FIXTURES`, `cli_runner`, `sample_audit_result`,
  `populated_history_dir` — TD-2
- `pip install shopify-image-audit` no longer pulls WeasyPrint; PDF
  export moved to optional `[pdf]` extra (`shopify-image-audit[pdf]`)
  — TD-4
- `src/audit/report.py::render_pdf_report` raises a friendly
  `ImportError` with install instructions when WeasyPrint is missing
  — TD-4
- `docs/tutorial.md` — 6-step "from install to delivered report in <5min"
  walkthrough — TD-4
- `MANIFEST.in` (NEW) ships CHANGELOG, CONTRIBUTING, README — TD-4

### Changed
- Test files: removed 8 duplicated `REPO_ROOT` declarations, 6 stale
  `sys.path.insert()` calls — TD-2
- `fixtures/` and `tests/fixtures/` consolidated (was inconsistent —
  `test_core` pointed elsewhere) — TD-2

### Stats
- 665 tests pass (up from 656)
- Ruff clean
- Single concurrency primitive (`run_parallel`) replaces two copies
- Test fixtures consolidated into one place

[0.14.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.0...v0.6.1

---

## [0.6.1] - 2026-07-31

### Fixed
- `_version.py` was not shipped in the wheel (`packages.find` didn't
  discover bare top-level modules). Added `[tool.setuptools]
  py-modules = ["_version"]`; verified to appear in `RECORD`.
- `_version.get_version()` now reads `importlib.metadata.version()` as
  primary path (works for pip/pipx/wheel installs), with `pyproject.toml`
  parsing as a development-checkout fallback, then `"unknown"`.
- `--no-cache` flag was documented but unimplemented on `audit measure`
  and `audit compare`. Flag added; `ResponseCache` plumbed through
  `fetch_url_as_audit()` and `fetch_lighthouse_json()`. Live-URL CLI
  tests updated to pass `--no-cache` to avoid cross-test cache leakage.
- `CHANGELOG.md` had two `[Unreleased]` reference definitions; removed
  the stale one.

### Stats
- 642 tests pass (no regression)
- Ruff clean

[Unreleased]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.0...v0.6.1

---

## [0.4.0] - 2026-07-30

### Added (Sprint 5)
- Snapshot testing infrastructure (syrupy) — 22 golden files covering 9 deterministic HTML renderers — TD-1
- CLI coverage close-out: every one of the 10 Typer commands now has at least one happy-path test in `tests/test_cli.py` / `tests/test_cli_coverage.py` — TD-2
- `audit history diff <store> --from <id> --to <id>` — diff any two historical snapshots and emit a comparison HTML — TD-4
- Stable `HistoryEntry.id` (12-char SHA-256 prefix of snapshot bytes, independent of filename/timestamp)
- `HistoryStore.get_by_id(hostname, id)` and `HistoryStore.compare_entries(hostname, id_a, id_b)` primitives
- `generate_diff_html(hostname, entry_a, entry_b, comparison)` — diff renderer with vitals table, image-stats table, ROI summary
- `validate_out_path()` now applied to `_history_show` and `_history_diff` `--output` flags (DX polish)
- `CHANGELOG.md` (this file)
- `--cov-fail-under=85` enforced in CI (current coverage: 91.24%)

### Changed
- All inline `try/except` boilerplate in `cli.py` replaced with the documented error decorators (`@handle_pipeline_errors`, `@handle_compare_errors`, `@handle_json_errors`, new `@handle_shopify_errors`) — `-58` lines net
- `RuntimeError` exit code now consistently **10** across all commands (was: 2 in `extract`/`score`/`report`/`shopify`)
- `cli.py` `809 → 751` lines

### Stats
- 546 tests (up from 489)
- 91.24% coverage (above 85% threshold)
- Ruff clean
- Trusted publishing on PyPI

[0.4.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.1.0-sprint1...v0.2.0
[0.1.0]: https://github.com/xopsio/shopify-image-audit/releases/tag/v0.1.0-sprint1

---

## [0.3.0] - 2026-07-30

### Added (Sprint 4)
- Branded report templates — `--brand-logo <path>` and `--brand-color <hex>` on `audit report` and `audit compare -o`
- ROI-ranked recommendations — new `ComparisonRecommendation` model with `sort_key` based on estimated conversion uplift; improvements sorted descending by ROI, regressions ascending
- Audit history storage — `HistoryStore` records each `audit baseline` to `~/.local/share/.shopify-image-audit/history/<hostname>/`
- `audit history list <hostname>` — Rich table of past audits
- `audit history show <hostname>` — trend HTML report
- `--history-dir <path>` and `--label <text>` flags on `audit baseline`
- PDF rendering hardened — restricted URL fetcher (data: only) for safer PDFs
- WeasyPrint constrained to `>=69.0,<70` for reproducibility

### Changed
- `ComparisonSummary` now has a structured `recommendations` field (backward-compatible `top_improvements`/`top_regressions` derived from it)
- Baseline command auto-records to audit history; failures are warnings, not errors

### Stats
- 489 tests (up from 390)
- Ruff clean
- Trusted publishing active for PyPI (`xopsio/shopify-image-audit`)

---

## [0.2.0] - 2026-07-30

### Added (Sprint 3)
- PDF export via `--pdf` flag (`audit report --pdf`, `audit compare -o foo.html --pdf`)
- Per-image before/after deltas with 2-phase matching (hash + src fallback)
- Shopify Admin API integration: `audit shopify auth` and `audit shopify inventory`
- v0.2.0 release prep: trusted publishing, hardened release workflow
- Structural build/publish split in release workflow (job-level if instead of shell dry_run)
- `workflow_dispatch` trigger on release workflow for manual dry runs

### Stats
- 390 tests (up from 276)
- 4 PRs merged (TD-1 through TD-4)

---

## [0.1.0] - 2026-07-29

### Added (Sprints 1 + 2)
- `audit run <url>` — full Lighthouse + audit pipeline
- `audit extract <lighthouse.json>` — image + LCP feature extraction
- `audit score <audit_input.json> --ranker {heuristic|ml}` — image scoring with two rankers
- `audit report <audit_result.json>` — HTML report generation
- `audit measure <url>` — live PageSpeed Insights metrics
- `audit baseline <lhr.json> --save <path>` — capture reusable baseline
- `audit compare <baseline> <current>` — before/after comparison (file or URL)
- PageSpeed Insights integration with rate-limit handling
- Pydantic v2 models with JSON schema contract (`schemas/audit_result.schema.json`)
- ML-style ranker (`audit.ranker_ml`) — hand-coded weighted ensemble
- CI workflow (Python 3.11 + 3.12, ruff, pytest-cov)
- Branch protection on `main`
- Customer report template + onboarding guide

### Stats
- 276 tests at end of Sprint 2
- 8 issues closed as superseded
- 30+ merged PRs

---

## [0.5.0] - 2026-07-30

### Added (Sprint 6)
- `audit shopify batch --stores-file <path>` — multi-store inventory audit with `--parallel N` (concurrent workers) and `--stop-on-error` flag — TD-3
- `src/engine/batch.py` (NEW): `StoreConfig`, `parse_stores_file`, `run_batch`, `merge_inventory`
- `src/engine/_logging.py` (NEW, ~70 lines): centralised `logging.getLogger("shopify_image_audit")` with `LOG_LEVEL` env-var override — TD-4
- 6 structured log hooks (INFO at request, DEBUG per stage/branch, ERROR on subprocess failure) across `audit_orchestrator`, `engine.history`, `pagespeed_api`, `_run_lighthouse`, brand validators, role sanitiser
- `CONTRIBUTING.md` (NEW, ~150 lines): WeasyPrint install + snapshot workflow + release process + observability guide
- `tests/test_table_snapshots.py` (NEW, 16 tests): Rich Console captures for `_table.py` renderers — TD-1

### Changed
- CI coverage threshold: `--cov-fail-under=85` → `--cov-fail-under=90`
- Test isolation: zero `Path("foo")` writes or `os.chdir` in tests; all CLI output writes go through `tmp_path` or `monkeypatch.chdir` — TD-2
- `HistoryStore._prune()` now returns the prune count (was: `None`)

### Stats
- 606 tests (up from 546)
- 93% coverage (up from 91.24%)
- `_table.py` coverage 68% → 100%
- Ruff clean

---

## [0.6.0] - 2026-07-30

### Added (Sprint 7)
- `audit schedule list/add/remove/run-all` — scheduled re-audit via the
  external-cron model (Sprint 4's deferred work, finally shipped) — TD-1
- `src/engine/scheduler.py` (NEW): ScheduleConfig, ScheduleStore,
  run_all_schedules — reads `~/.shopify-image-audit/schedules.json` and
  records each fetch to `HistoryStore`
- `src/integrations/_cache.py` (NEW): on-disk PageSpeed response cache with
  TTL — `PAGESPEED_CACHE_TTL` env var (default 3600s; `0` disables) — TD-3
- `src/_version.py` (NEW): shared `get_version()` helper — fixes the
  long-standing report footer version drift (was hardcoded `v0.1`)
- `docs/runbook/scheduled_reaudit.md` (NEW): crontab snippet, systemd
  timer alternative, `flock` overlap-prevention, env-var reference, security
  notes, troubleshooting
- Dependabot config (`.github/dependabot.yml`) — weekly pip + GitHub
  Actions updates with grouped minor+patch — TD-2
- SLSA build-provenance attestation on every PyPI release (best-effort,
  non-blocking) — TD-2

### Changed
- CLI spec (`docs/spec/cli_v0_1.md`) rewritten to document all 11 actual
  commands (was: 8) — TD-4
- `README.md`: added `pipx install` Deployment section, fixed test-count
  drift (3 different numbers → 1 consistent), added Lighthouse CLI
  prerequisite note
- `docs/runbook/measurement_protocol.md`: corrected the `--runs`
  semantics (last run, not median) — TD-4
- Runtime deps: upper caps on `pydantic`, `typer`, `rich`, `requests`,
  `jsonschema` (matches existing `weasyprint` pinning pattern) — TD-2

### Stats
- 642 tests (up from 606)
- Ruff clean
- Trusted publishing + provenance attestation active for PyPI

[0.6.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.1.0-sprint1...v0.2.0
[0.1.0]: https://github.com/xopsio/shopify-image-audit/releases/tag/v0.1.0-sprint1