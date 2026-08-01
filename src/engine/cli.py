"""
Typer-based CLI for Shopify Image Audit.

Matches docs/spec/cli_v0_1.md contract:
    audit run <url> [options]
    audit extract <lighthouse.json>
    audit score <audit_input.json>
    audit report <audit_result.json>

The console-script entry point is ``audit`` (see pyproject.toml),
so the user invokes:
    audit run https://example.myshopify.com --device mobile --runs 3

Exit codes (spec):
    0 - success
    2 - invalid arguments
    10 - lighthouse failure

Architecture: command bodies are thin; reusable logic lives in
``engine.cli_helpers`` (validators, dispatchers, table renderers,
error-handling decorators). Keep that split.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer
from rich import print as rprint
from rich.console import Console

from audit.models import AuditResult
from audit.report import generate_html_report, write_html_report

# NOTE: imported as ``run_comparison`` to avoid shadowing the Typer command
# function below (also named ``compare``). The CLI exposes ``compare`` for the
# end-user-facing ``audit compare`` subcommand; the underlying engine function
# is the actual comparison logic from ``core.baseline_manager``.
from core.baseline_manager import compare as run_comparison
from core.baseline_manager import save_baseline
from engine.audit_orchestrator import run_audit
from engine.cli_helpers._dispatchers import fetch_url_as_audit, load_or_audit_file
from engine.cli_helpers._errors import (
    handle_compare_errors,
    handle_json_errors,
    handle_pipeline_errors,
    handle_shopify_errors,
)
from engine.cli_helpers._suggest import format_suggestion
from engine.cli_helpers._table import (
    print_audit_results,
    print_audit_summary,
    print_comparison_summary,
    print_comparison_table,
)
from engine.cli_helpers._validators import (
    require_exists,
    validate_measure_url,
    validate_out_path,
    validate_run_url,
)
from engine.config import get_config
from engine.history import HistoryStore
from integrations._cache import ResponseCache
from integrations.pagespeed_api import PageSpeedAPIClient
from integrations.shopify_admin import ShopifyAdminClient

# --- Exit codes per spec ---------------------------------------------------
EXIT_OK = 0
EXIT_INVALID_ARGS = 2
EXIT_LIGHTHOUSE_FAILURE = 10


def _get_version() -> str:
    """Read the package version from pyproject.toml at runtime.

    Delegates to the shared ``src/_version.py`` helper so both the CLI
    and the HTML report footer read from one place.
    """
    from _version import get_version

    return get_version()


_VERSION = _get_version()

console = Console()

# ---- repo-level paths -----------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "audit_result.schema.json"


# ---------------------------------------------------------------------------
# Top-level app - NO nested "audit" group so that `audit run` works
# directly from the console-script named ``audit``.
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="audit",
    help="Shopify store image audit - Lighthouse-based analysis with heuristic and ML scoring.",
    add_completion=False,
)

#: Cached user config (config.toml) — see engine/config.py. Precedence at
#: each call site: CLI flag > env var > config > built-in default.
_cfg = get_config


# ---------------------------------------------------------------------------
# Lighthouse helper (kept inline — requires subprocess + external CLI)
# ---------------------------------------------------------------------------


def _resolve_lighthouse_binary(explicit_path: str | None) -> Path:
    """Resolve the Lighthouse CLI path with the documented precedence.

    Precedence: ``--lighthouse-bin`` > ``$LIGHTHOUSE_BIN`` > ``shutil.which("lighthouse")``.

    Returns the resolved Path on success. Raises ``typer.Exit(EXIT_LIGHTHOUSE_FAILURE)``
    with a multi-line help message when nothing can be found.
    """
    if explicit_path:
        candidate = Path(explicit_path)
        if not candidate.is_file():
            rprint(f"[red]Error:[/red] --lighthouse-bin points to a non-existent file: {candidate}")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None
        return candidate

    env_bin = os.environ.get("LIGHTHOUSE_BIN")
    if env_bin:
        candidate = Path(env_bin)
        if not candidate.is_file():
            rprint(f"[red]Error:[/red] $LIGHTHOUSE_BIN points to a non-existent file: {candidate}")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None
        return candidate

    on_path = shutil.which("lighthouse")
    if on_path:
        return Path(on_path)

    rprint(
        "[red]Error:[/red] `lighthouse` CLI not found. To fix:\n"
        "  1. Install: npm i -g lighthouse  (Node ≥ 18)\n"
        "  2. Set LIGHTHOUSE_BIN=/path/to/lighthouse\n"
        "  3. Pass --lighthouse-bin /path/to/lighthouse\n"
        "  4. Or use --lhr <file> with a pre-existing Lighthouse report\n"
        "  Docs: docs/integrations/LIGHTHOUSE.md"
    )
    raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None


# 10 minute per-run timeout — long enough for slow Shopify storefronts,
# short enough to fail fast on a stuck headless Chrome.
_LIGHTHOUSE_TIMEOUT_SECONDS = 600


def _run_lighthouse(
    url: str,
    *,
    device: str,
    runs: int,
    out_dir: Path,
    lighthouse_bin: Path | None = None,
) -> Path:
    """Run Lighthouse CLI and return the path to the best JSON report.

    ``lighthouse_bin`` overrides the resolution chain (``--lighthouse-bin``,
    ``$LIGHTHOUSE_BIN``, ``shutil.which``). Raises
    ``typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE)`` on any failure (missing
    binary, non-zero exit, subprocess timeout).
    """
    lh_bin = lighthouse_bin or _resolve_lighthouse_binary(None)

    out_dir.mkdir(parents=True, exist_ok=True)

    form_factor = "desktop" if device == "desktop" else "mobile"
    emulated = "none" if device == "desktop" else "mobile"

    best_path: Path | None = None
    from engine._logging import get_logger

    _lh_log = get_logger()
    for i in range(1, runs + 1):
        out_file = out_dir / f"lhr_run{i}.json"
        cmd = [
            str(lh_bin),
            url,
            "--output=json",
            f"--output-path={out_file}",
            f"--preset={form_factor}",
            f"--emulated-form-factor={emulated}",
            "--only-categories=performance",
            "--chrome-flags=--headless",
        ]
        rprint(f"[cyan]Lighthouse run {i}/{runs}[/cyan]")
        _lh_log.info("Lighthouse run %d/%d: %s", i, runs, url)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=_LIGHTHOUSE_TIMEOUT_SECONDS)
        except subprocess.CalledProcessError as exc:
            _lh_log.error("Lighthouse run %d failed: %s", i, exc.stderr[:500])
            rprint(f"[red]Lighthouse failed (run {i}):[/red] {exc.stderr[:500]}")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from exc
        except subprocess.TimeoutExpired as exc:
            _lh_log.error("Lighthouse run %d timed out after %ss", i, _LIGHTHOUSE_TIMEOUT_SECONDS)
            rprint(f"[red]Lighthouse timed out (run {i}) after {_LIGHTHOUSE_TIMEOUT_SECONDS}s[/red]")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from exc
        best_path = out_file  # simple: use the last successful run

    assert best_path is not None
    return best_path


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
@handle_pipeline_errors(step_name="run")
def run(
    url: str = typer.Argument(..., help="Shopify store URL to audit."),
    device: str | None = typer.Option(
        None,
        "--device",
        help="Device type: mobile or desktop (default: config or mobile).",
    ),
    runs: int = typer.Option(3, "--runs", help="Number of Lighthouse runs (default 3)."),
    out_dir: Path = typer.Option("artifacts", "--out-dir", help="Directory for output artifacts."),
    lhr: Path | None = typer.Option(None, "--lhr", help="Use an existing Lighthouse JSON instead of running live."),
    lighthouse_bin: Path | None = typer.Option(
        None,
        "--lighthouse-bin",
        envvar="LIGHTHOUSE_BIN",
        help="Path to the lighthouse CLI binary (default: $LIGHTHOUSE_BIN or PATH).",
    ),
) -> None:
    """Run Lighthouse audit on <url>, analyse images, and write results."""
    # --- resolve config defaults (flag > env > config > default) ---
    if device is None:
        device = _cfg().defaults.device

    # --- validate URL scheme ---
    validate_run_url(url)

    # --- validate --out-dir safety ---
    validate_out_path(out_dir, label="--out-dir")

    # --- validate args ---
    if device not in ("mobile", "desktop"):
        rprint(
            f"[red]Error:[/red] --device must be 'mobile' or 'desktop', "
            f"got '{device}'.{format_suggestion(device, ['mobile', 'desktop'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if runs < 1:
        rprint("[red]Error:[/red] --runs must be >= 1.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- resolve lighthouse binary path: --lighthouse-bin > $LIGHTHOUSE_BIN > PATH ---
    if lhr is None and lighthouse_bin is None and os.environ.get("LIGHTHOUSE_BIN"):
        lighthouse_bin = Path(os.environ["LIGHTHOUSE_BIN"])

    # --- obtain LHR JSON ---
    if lhr is not None:
        json_path: Path = require_exists(lhr)
    else:
        json_path = _run_lighthouse(
            url,
            device=device,
            runs=runs,
            out_dir=out_dir,
            lighthouse_bin=lighthouse_bin,
        )

    # --- run the audit pipeline (errors caught by @handle_pipeline_errors) ---
    result: AuditResult = run_audit(json_path, url=url, device=device, runs=runs)

    # --- pretty table ---
    print_audit_results(result, console=console)
    print_audit_summary(result)

    # --- write JSON result ---
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    result_file = Path(out_dir) / "audit_result.json"
    result_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    rprint(f"\n[green]Result written to {result_file}[/green]")

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


@app.command()
def measure(
    url: str = typer.Argument(..., help="URL to measure with PageSpeed Insights."),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Strategy: mobile or desktop (default: config or mobile).",
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", envvar="PAGESPEED_API_KEY", help="Google Cloud API key (optional, or set PAGESPEED_API_KEY)."
    ),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output JSON file (default: print to stdout)."),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the on-disk PageSpeed response cache (always fetch fresh).",
    ),
) -> None:
    """Fetch live performance metrics from Google PageSpeed Insights API."""
    # --- resolve config defaults (flag > env > config > default) ---
    if strategy is None:
        strategy = _cfg().defaults.strategy
    if api_key is None:
        api_key = _cfg().pagespeed.api_key

    # --- validate URL (allow scheme-less for normalization by API) ---
    validate_measure_url(url)

    # --- validate strategy ---
    if strategy not in ("mobile", "desktop"):
        rprint(
            f"[red]Error:[/red] --strategy must be 'mobile' or 'desktop', "
            f"got '{strategy}'.{format_suggestion(strategy, ['mobile', 'desktop'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- validate output path safety ---
    if output is not None:
        validate_out_path(output)

    # --- fetch metrics (consult cache unless --no-cache) ---
    cache = None if no_cache else _build_pagespeed_cache()
    client = PageSpeedAPIClient(api_key=api_key, cache=cache)
    metrics = client.get_metrics(url, strategy=strategy)

    # --- output ---
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")
        rprint(f"[green]Metrics written to {output_path}[/green]")
    else:
        print(json.dumps(metrics.to_dict(), indent=2))

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# shopify
# ---------------------------------------------------------------------------


@app.command(name="shopify")
def shopify(
    subcommand: str = typer.Argument(..., help="Subcommand: 'auth', 'inventory', 'batch', or 'login'."),
    shop_domain: str = typer.Argument(
        None,
        help="Your shop domain, e.g. 'store.myshopify.com'. Omit when --stores-file is provided.",
    ),
    access_token: str | None = typer.Option(
        None,
        "--access-token",
        help="Admin API access token. Required for 'auth' and single-store 'inventory'.",
        envvar="SHOPIFY_ACCESS_TOKEN",
    ),
    output: Path = typer.Option(
        None,
        "-o",
        "--output",
        help="[inventory/batch] Write the inventory JSON to this file.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        help="[inventory] Maximum products to fetch (1-250, default 50).",
    ),
    stores_file: Path | None = typer.Option(
        None,
        "--stores-file",
        help="[batch] Path to a JSON file listing stores to audit. "
        "Each entry must have 'shop_domain'; 'access_token' is optional "
        "(falls back to tokens.json from `audit shopify login`).",
    ),
    parallel: int | None = typer.Option(
        None,
        "--parallel",
        help="[batch] Number of concurrent store audits. 0 = unlimited (default: config or 1).",
    ),
    stop_on_error: bool = typer.Option(
        False,
        "--stop-on-error",
        help="[batch] Abort on the first store failure (default: continue past failures).",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        envvar="SHOPIFY_CLIENT_ID",
        help="[login] OAuth client_id from your Shopify custom app.",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        envvar="SHOPIFY_CLIENT_SECRET",
        help="[login] OAuth client_secret from your Shopify custom app.",
    ),
    scopes: str | None = typer.Option(
        None,
        "--scopes",
        envvar="SHOPIFY_OAUTH_SCOPES",
        help="[login] Comma-separated scope list (default: config [shopify] scopes).",
    ),
) -> None:
    """Interact with a Shopify store via the Admin API (auth, inventory, batch, login)."""
    # --- resolve config defaults (flag > env > config > default) ---
    if access_token is None:
        access_token = _cfg().shopify.access_token
    # `parallel == 0` is a valid "unlimited" value — never `or`-coalesce it.
    if parallel is None:
        parallel = _cfg().defaults.parallel
    if client_id is None:
        client_id = _cfg().shopify.client_id
    if client_secret is None:
        client_secret = _cfg().shopify.client_secret
    if scopes is None:
        scopes = _cfg().shopify.scopes

    if subcommand not in ("auth", "inventory", "batch", "login"):
        rprint(
            f"[red]Error:[/red] Unknown shopify subcommand: {subcommand!r} "
            f"(use 'auth', 'inventory', 'batch', or 'login')."
            f"{format_suggestion(subcommand, ['auth', 'inventory', 'batch', 'login'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # ``login`` opens the OAuth browser flow and stores the resulting
    # token; it does not need shop_domain / access_token flags.
    if subcommand == "login":
        _shopify_login(
            shop_domain=shop_domain,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        raise typer.Exit(code=EXIT_OK) from None

    # batch subcommand has its own dispatch path
    if subcommand == "batch":
        _shopify_batch(
            stores_file=stores_file,
            output=output,
            parallel=parallel,
            stop_on_error=stop_on_error,
        )
        raise typer.Exit(code=EXIT_OK) from None

    # auth / inventory require a single token. Fall back to the persisted
    # ``TokensStore`` if no token was supplied on the command line or
    # via env/config — this is how ``audit shopify auth <store>`` works
    # after a successful ``audit shopify login <store>``.
    if access_token is None and shop_domain is not None:
        from engine.tokens import TokensStore

        access_token = TokensStore().get(shop_domain)
        if access_token is None:
            rprint(
                f"[red]Error:[/red] No access token for {shop_domain}. "
                f"Run `audit shopify login {shop_domain}` or pass --access-token."
            )
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # auth / inventory require a single token
    if shop_domain is None:
        rprint(f"[red]Error:[/red] `audit shopify {subcommand}` requires a shop_domain.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if access_token is None:
        rprint(f"[red]Error:[/red] `audit shopify {subcommand}` requires an access token.")
        rprint("Pass it via --access-token or $SHOPIFY_ACCESS_TOKEN.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if subcommand == "auth":
        _shopify_auth(shop_domain, access_token)
    else:  # inventory
        if output is not None:
            validate_out_path(output)
        _shopify_inventory(shop_domain, access_token, output, limit)

    raise typer.Exit(code=EXIT_OK) from None


def _shopify_batch(
    *,
    stores_file: Path | None,
    output: Path | None,
    parallel: int,
    stop_on_error: bool,
) -> None:
    """Run an inventory audit across multiple stores from a JSON file."""
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from engine.batch import merge_inventory, parse_stores_file, run_batch

    if stores_file is None:
        rprint("[red]Error:[/red] `audit shopify batch` requires --stores-file.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if parallel < 0:
        rprint(f"[red]Error:[/red] --parallel must be >= 0, got {parallel}.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    try:
        stores = parse_stores_file(stores_file)
    except (FileNotFoundError, ValueError) as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if not stores:
        rprint(f"[yellow]No stores found in {stores_file}.[/yellow]")
        raise typer.Exit(code=EXIT_OK) from None

    rprint(
        f"[cyan]Running batch for {len(stores)} store(s) "
        f"(parallel={parallel if parallel > 0 else len(stores)}, "
        f"stop_on_error={stop_on_error})...[/cyan]"
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("shopify batch", total=len(stores))

        def _on_done(store: object, _result: object) -> None:
            # Description shows the last-completed store; the bar + counter
            # communicate aggregate progress. `store_domain` is the natural
            # identifier (StoreConfig exposes it as .shop_domain).
            progress.update(task_id, advance=1, description=getattr(store, "shop_domain", ""))

        batch_result = run_batch(
            stores,
            parallel=parallel,
            stop_on_error=stop_on_error,
            on_done=_on_done,
        )

    for r in batch_result.results:
        if r.success:
            rprint(f"  [green]✓[/green] {r.shop_domain}: {len(r.inventory)} images")
        else:
            rprint(f"  [red]✗[/red] {r.shop_domain}: {r.error}")

    inventory = merge_inventory(batch_result.results)

    if output is not None:
        validate_out_path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(inventory, indent=2),
            encoding="utf-8",
        )
        rprint(
            f"[green]Batch inventory written to {output}[/green] ({len(inventory)} images from {len(stores)} store(s))"
        )
    else:
        # Print combined inventory to stdout
        rprint(json.dumps(inventory, indent=2))

    if batch_result.all_failed:
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None


@handle_shopify_errors()
def _shopify_login(
    shop_domain: str | None,
    *,
    client_id: str | None,
    client_secret: str | None,
    scopes: str | None,
) -> None:
    """Run the OAuth authorization-code flow against the Shopify Admin API.

    Opens the user's browser to the Shopify authorize URL, waits on a
    local HTTP server for the redirect, exchanges the temporary code for
    a permanent access token, and stores the token in ``TokensStore``
    (default: ``~/.local/share/.shopify-image-audit/tokens.json``).
    """
    import webbrowser

    from engine.tokens import TokensStore
    from integrations.oauth_callback_server import OAuthCallbackServer
    from integrations.shopify_oauth import (
        DEFAULT_SCOPES,
        build_authorize_url,
        exchange_code_for_token,
        generate_state,
    )

    if shop_domain is None:
        rprint(
            "[red]Error:[/red] `audit shopify login` requires a shop_domain "
            "(e.g. `audit shopify login mystore.myshopify.com`)."
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if not client_id or not client_secret:
        rprint(
            "[red]Error:[/red] OAuth credentials missing. "
            "Pass --client-id / --client-secret, set $SHOPIFY_CLIENT_ID / "
            "$SHOPIFY_CLIENT_SECRET, or configure [shopify] in config.toml."
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    effective_scopes = scopes or DEFAULT_SCOPES

    state = generate_state()
    with OAuthCallbackServer(state, timeout=60.0) as server:
        redirect_uri = server.callback_url
        authorize_url = build_authorize_url(
            shop=shop_domain,
            client_id=client_id,
            scopes=effective_scopes,
            redirect_uri=redirect_uri,
            state=state,
        )

        rprint(f"[cyan]Opening browser to authorize {shop_domain}…[/cyan]")
        rprint(f"  Authorize URL: {authorize_url}")
        if not webbrowser.open(authorize_url):
            rprint(
                "[yellow]Browser failed to open.[/yellow] Copy the URL above "
                "into a browser, or use the headless-mode hint in "
                "`docs/integrations/SHOPIFY_OAUTH.md`."
            )

        rprint(f"[dim]Listening on {redirect_uri} (timeout 60s)…[/dim]")
        code = server.wait_for_code()

        if code is None:
            err = server.last_error()
            if err:
                rprint(f"[red]OAuth denied:[/red] {err}")
            else:
                rprint(
                    "[red]OAuth timed out[/red] — no callback received "
                    "within 60 seconds. Re-run and complete the browser step."
                )
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    try:
        token = exchange_code_for_token(
            shop=shop_domain,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
        )
    except RuntimeError as exc:
        rprint(f"[red]Token exchange failed:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc

    path = TokensStore().set(shop_domain, token)
    rprint(f"[green]✓ Authorised {shop_domain}[/green]")
    rprint(f"  Token stored in {path}")
    rprint(f"  Next: `audit shopify auth {shop_domain}` or `audit shopify inventory {shop_domain}`.")


@handle_shopify_errors()
def _shopify_auth(shop_domain: str, access_token: str) -> None:
    """Verify an Admin API access token by fetching shop info."""
    client = ShopifyAdminClient(shop_domain, access_token)
    info = client.get_shop_info()

    rprint("[green]✓ Token valid[/green]")
    rprint(f"  Name:     {info['name']}")
    rprint(f"  Domain:   {info['domain']}")
    rprint(f"  Plan:     {info['plan']}")
    rprint(f"  Currency: {info['currency']}")


@handle_shopify_errors()
def _shopify_inventory(
    shop_domain: str,
    access_token: str,
    output: Path | None,
    limit: int,
) -> None:
    """List image URLs in a Shopify store: products + theme assets."""
    client = ShopifyAdminClient(shop_domain, access_token)
    products = client.get_products(limit=limit)
    theme_assets = client.get_theme_assets()

    # Build the unified inventory list.
    inventory: list[dict[str, Any]] = []
    for p in products:
        if p.get("image_url"):
            inventory.append(
                {
                    "source": "product",
                    "title": p["title"],
                    "url": p["image_url"],
                }
            )
    for a in theme_assets:
        inventory.append(
            {
                "source": "theme_asset",
                "theme": a["theme_name"],
                "key": a["key"],
                "url": a["url"],
            }
        )

    if output is not None:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            json.dumps(inventory, indent=2),
            encoding="utf-8",
        )
        rprint(f"[green]Inventory written to {output}[/green] ({len(inventory)} images)")
    else:
        rprint(f"[green]✓ Inventory fetched[/green] ({len(products)} products, {len(theme_assets)} theme assets)")
        for item in inventory:
            rprint(f"  [{item['source']:11}] {item['url']}")


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@app.command()
def history(
    subcommand: str = typer.Argument(..., help="Subcommand: 'list', 'show', or 'diff'."),
    hostname: str = typer.Argument(..., help="Store hostname, e.g. 'mystore.myshopify.com'."),
    history_dir: Path | None = typer.Option(
        None,
        "--history-dir",
        help="Override the audit-history directory (default: $XDG_DATA_HOME/.shopify-image-audit/history/).",
    ),
    output: Path | None = typer.Option(
        None,
        "-o",
        "--output",
        help="[show/diff] Output HTML file path.",
    ),
    id_a: str | None = typer.Option(
        None,
        "--from",
        help="[diff] Source entry id (the older 'before' snapshot).",
    ),
    id_b: str | None = typer.Option(
        None,
        "--to",
        help="[diff] Target entry id (the newer 'after' snapshot).",
    ),
) -> None:
    """Inspect audit history for a store: list, trend report, or diff two snapshots.

    Requires at least one recorded baseline (via ``audit baseline``) for the store.
    """
    # --- resolve config defaults (flag > env > config > default) ---
    if history_dir is None:
        cfg_history = _cfg().history.history_dir
        if cfg_history is not None:
            history_dir = Path(cfg_history)

    if subcommand not in ("list", "show", "diff"):
        rprint(
            f"[red]Error:[/red] Unknown history subcommand: {subcommand!r} "
            f"(use 'list', 'show', or 'diff')."
            f"{format_suggestion(subcommand, ['list', 'show', 'diff'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    store = HistoryStore(base_dir=history_dir)

    try:
        entries = store.list_entries(hostname)
    except Exception as exc:
        rprint(f"[red]Error:[/red] Failed to read history: {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if not entries:
        rprint(f"[yellow]No history entries found for {hostname!r}.[/yellow]")
        rprint("  Run `audit baseline` first to record a snapshot.")
        raise typer.Exit(code=EXIT_OK) from None

    if subcommand == "list":
        _history_list(hostname, entries)
    elif subcommand == "show":
        _history_show(hostname, entries, output=output)
    else:  # diff
        if not id_a or not id_b:
            rprint("[red]Error:[/red] `audit history diff` requires --from <id> and --to <id>.")
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None
        _history_diff(store, hostname, id_a, id_b, output=output)

    raise typer.Exit(code=EXIT_OK) from None


def _history_list(hostname: str, entries: list[Any]) -> None:
    """Print a table of history entries for a hostname."""
    from rich.table import Table

    table = Table(title=f"Audit History — {hostname}")
    table.add_column("#", style="dim")
    table.add_column("Timestamp")
    table.add_column("Label")
    table.add_column("LCP", justify="right")
    table.add_column("CLS", justify="right")
    table.add_column("INP", justify="right")
    table.add_column("Images", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Score", justify="right")

    for idx, entry in enumerate(entries, start=1):
        label = entry.label or "—"
        lcp_display = f"{entry.lcp_ms:.0f}ms"
        cls_display = f"{entry.cls:.3f}"
        inp_display = f"{entry.inp_ms:.0f}ms"
        ts = entry.timestamp_utc.replace("T", " ")[:19]
        table.add_row(
            str(idx),
            ts,
            label,
            lcp_display,
            cls_display,
            inp_display,
            str(entry.image_count),
            f"{entry.total_bytes / 1024:.0f} KB",
            f"{entry.avg_score:.0f}",
        )

    console = Console()
    console.print(table)


def _history_show(hostname: str, entries: list[Any], *, output: Path | None = None) -> None:
    """Generate a trend HTML report for a hostname's audit history."""
    from engine.history import generate_trend_html

    html = generate_trend_html(hostname, entries)

    if output is None:
        out = Path(f"{hostname}-history.html")
    else:
        # Validate the user-supplied path through the standard safety helper.
        validate_out_path(output)
        out = output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    rprint(f"[green]Trend report written to {out}[/green]")


def _history_diff(
    store: HistoryStore,
    hostname: str,
    id_a: str,
    id_b: str,
    *,
    output: Path | None = None,
) -> None:
    """Diff two historical snapshots and write a comparison HTML report."""
    entry_a = store.get_by_id(hostname, id_a)
    entry_b = store.get_by_id(hostname, id_b)
    if entry_a is None or entry_b is None:
        missing = []
        if entry_a is None:
            missing.append(id_a)
        if entry_b is None:
            missing.append(id_b)
        rprint(f"[red]Error:[/red] Entry id(s) not found for {hostname!r}: {', '.join(missing)}.")
        rprint("  Use `audit history list` to see available entry ids.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    comparison = store.compare_entries(hostname, id_a, id_b)
    if comparison is None:
        rprint("[red]Error:[/red] Failed to compute comparison.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    from engine.history import generate_diff_html

    html = generate_diff_html(hostname, entry_a, entry_b, comparison)

    if output is None:
        output = Path(f"{hostname}-diff-{id_a[:6]}-{id_b[:6]}.html")
    else:
        # Validate the output path through the standard safety helper.
        validate_out_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    rprint(f"[green]Diff report written to {output}[/green]")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


@app.command()
@handle_json_errors("lighthouse_json")
def extract(
    lighthouse_json: Path = typer.Argument(..., help="Path to a Lighthouse JSON report."),
) -> None:
    """Extract image + LCP-related features into an intermediate JSON."""
    if not lighthouse_json.exists():
        rprint(f"[red]Error:[/red] File not found: {lighthouse_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    from audit.parser import parse

    with open(lighthouse_json, encoding="utf-8") as f:
        raw = json.load(f)

    images = parse(raw)
    print(json.dumps(images, indent=2))

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------


@app.command()
@handle_json_errors("audit_input_json")
def score(
    audit_input_json: Path = typer.Argument(..., help="Path to intermediate audit input JSON."),
    ranker: str = typer.Option("heuristic", "--ranker", help="Scoring algorithm: 'heuristic' (default) or 'ml'."),
) -> None:
    """Assign role, score (0-100), and recommendations to each image."""
    if not audit_input_json.exists():
        rprint(f"[red]Error:[/red] File not found: {audit_input_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if ranker not in ("heuristic", "ml"):
        rprint(
            f"[red]Error:[/red] --ranker must be 'heuristic' or 'ml', "
            f"got '{ranker}'.{format_suggestion(ranker, ['heuristic', 'ml'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if ranker == "ml":
        from audit.ranker_ml import rank
    else:
        from audit.ranker_heuristic import rank

    with open(audit_input_json, encoding="utf-8") as f:
        images = json.load(f)

    scored = rank(images)
    print(json.dumps(scored, indent=2))

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@app.command()
def report(
    audit_result_json: Path = typer.Argument(..., help="Path to audit_result.json."),
    output: Path | None = typer.Option(
        None,
        "-o",
        "--output",
        help="Output file (HTML or PDF based on --pdf; default: config or report.html).",
    ),
    pdf: bool = typer.Option(False, "--pdf", help="Render the report as PDF instead of HTML."),
    brand_logo: Path | None = typer.Option(
        None,
        "--brand-logo",
        help="Path to a brand logo (PNG, JPG, GIF, WebP, SVG). Embedded in the report header as a data URI.",
    ),
    brand_color: str | None = typer.Option(
        None,
        "--brand-color",
        help="Brand primary colour as a hex string (e.g. '#ff6b35'). Invalid values are ignored.",
    ),
) -> None:
    """Render an audit result JSON to an HTML report (or PDF with --pdf)."""
    from audit.report import _parse_brand_color, _read_brand_logo

    # --- resolve config defaults (flag > env > config > default) ---
    cfg = _cfg()
    if output is None:
        output = Path(cfg.report.output)
    if brand_logo is None and cfg.report.brand_logo is not None:
        brand_logo = Path(cfg.report.brand_logo)
    if brand_color is None:
        brand_color = cfg.report.brand_color

    if not audit_result_json.exists():
        rprint(f"[red]Error:[/red] File not found: {audit_result_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # Validate brand colour; warn (don't fail) on invalid input.
    validated_color = _parse_brand_color(brand_color) if brand_color else None
    if brand_color and validated_color is None:
        rprint(f"[yellow]Warning:[/yellow] Ignoring invalid --brand-color {brand_color!r}; using default palette.")
    # Validate brand logo; warn (don't fail) on missing/invalid.
    validated_logo = _read_brand_logo(brand_logo) if brand_logo else None
    if brand_logo and validated_logo is None:
        rprint(f"[yellow]Warning:[/yellow] Could not read --brand-logo {brand_logo!r}; rendering without logo.")

    # If --pdf is set and the user didn't pass --output, default to .pdf.
    # We can't mutate the Option default based on another flag in Typer,
    # so we adjust the resolved Path here.
    if pdf and output == Path("report.html"):
        output = output.with_suffix(".pdf")

    try:
        if pdf:
            # Render HTML in-memory, then convert to PDF. We don't use
            # write_html_report because that helper writes HTML directly.
            with open(audit_result_json, encoding="utf-8") as fh:
                raw = json.load(fh)
            from audit.report import generate_html_report, render_pdf_report

            html = generate_html_report(
                raw,
                brand_logo=validated_logo,
                brand_color=validated_color,
            )
            render_pdf_report(html, output)
            rprint(f"[green]OK[/green] PDF report written to: {output}")
        else:
            write_html_report(
                audit_result_json,
                output,
                brand_logo=brand_logo,
                brand_color=brand_color,
            )
            rprint(f"[green]OK[/green] HTML report written to: {output}")
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {audit_result_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except KeyError as e:
        rprint(f"[red]Error:[/red] Missing required field in audit result: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except RuntimeError as e:
        # PDF rendering can fail with RuntimeError if WeasyPrint can't
        # write the file (fontconfig / pango missing). Surface as exit 10
        # to match the convention used by other commands.
        rprint(f"[red]Error:[/red] Report rendering failed: {e}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to generate report: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


@app.command()
@handle_pipeline_errors(step_name="baseline")
def baseline(
    lhr_json: Path = typer.Argument(..., help="Path to a Lighthouse JSON / fixture report to use as the baseline."),
    save: Path = typer.Option(..., "--save", help="Where to write the baseline audit_result.json."),
    url: str | None = typer.Option(None, "--url", help="Override the store URL in the baseline meta."),
    device: str | None = typer.Option(
        None,
        "--device",
        help="Device type: mobile or desktop (default: config or mobile).",
    ),
    history_dir: Path | None = typer.Option(
        None,
        "--history-dir",
        help="Override the audit-history directory (default: $XDG_DATA_HOME/.shopify-image-audit/history/).",
    ),
    label: str | None = typer.Option(
        None,
        "--label",
        help="Optional label for the history entry (e.g. 'Pre-optimisation baseline').",
    ),
) -> None:
    """Run an audit on <lhr_json> and store it as a reusable baseline."""
    # --- resolve config defaults (flag > env > config > default) ---
    cfg = _cfg()
    if device is None:
        device = cfg.defaults.device
    if history_dir is None and cfg.history.history_dir is not None:
        history_dir = Path(cfg.history.history_dir)

    if not lhr_json.exists():
        rprint(f"[red]Error:[/red] File not found: {lhr_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if device not in ("mobile", "desktop"):
        rprint(
            f"[red]Error:[/red] --device must be 'mobile' or 'desktop', "
            f"got '{device}'.{format_suggestion(device, ['mobile', 'desktop'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- validate --save path safety ---
    validate_out_path(save)

    # Pipeline errors caught by @handle_pipeline_errors
    result: AuditResult = run_audit(lhr_json, url=url, device=device)

    save_baseline(result, save)
    rprint(f"[green]Baseline saved to {save}[/green]")
    rprint(
        f"  URL: {result.meta.url} | LCP: {result.vitals.lcp_ms:.0f}ms | "
        f"images: {len(result.images)} | {sum(i.bytes for i in result.images) / 1024:.0f} KB"
    )

    # --- record to audit history (never blocks the baseline) ---
    try:
        store = HistoryStore(base_dir=history_dir)
        history_path = store.record(result, label=label)
        rprint(f"[dim]Recorded to audit history: {history_path}[/dim]")
    except Exception as exc:
        rprint(f"[yellow]Warning:[/yellow] Failed to record audit history: {exc}")

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@app.command()
@handle_compare_errors()
def compare(
    baseline_json: Path = typer.Argument(..., help="Path to a baseline audit_result.json (from `audit baseline`)."),
    current: str = typer.Argument(..., help="Path to the current audit_result.json OR a live URL (https://...)."),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Write an HTML before/after report here (default: stdout JSON)."
    ),
    pdf: bool = typer.Option(False, "--pdf", help="When --output is set, render a PDF instead of HTML."),
    json_out: Path | None = typer.Option(None, "--json", help="Also write the comparison result JSON to this file."),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="PageSpeed strategy when <current> is a URL (default: config or mobile).",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="PAGESPEED_API_KEY",
        help="Google Cloud API key for PageSpeed (optional, or set PAGESPEED_API_KEY).",
    ),
    brand_logo: Path | None = typer.Option(
        None,
        "--brand-logo",
        help="Path to a brand logo (PNG, JPG, GIF, WebP, SVG). Used when -o/--pdf writes a report.",
    ),
    brand_color: str | None = typer.Option(
        None,
        "--brand-color",
        help="Brand primary colour as hex (e.g. '#ff6b35'). Invalid values are ignored.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass the on-disk PageSpeed response cache (always fetch fresh).",
    ),
) -> None:
    """Compare a baseline audit against a current audit (before/after).

    Each input may be a saved ``audit_result.json`` (from ``audit baseline``),
    a raw Lighthouse/fixture file, or a live URL (the latter is fetched via
    the PageSpeed Insights API). Mixing formats is fine: e.g. a saved
    baseline against a live URL.
    """
    if not baseline_json.exists():
        rprint(f"[red]Error:[/red] baseline file not found: {baseline_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- resolve config defaults (flag > env > config > default) ---
    cfg = _cfg()
    if strategy is None:
        strategy = cfg.defaults.strategy
    if api_key is None:
        api_key = cfg.pagespeed.api_key
    if brand_logo is None and cfg.report.brand_logo is not None:
        brand_logo = Path(cfg.report.brand_logo)
    if brand_color is None:
        brand_color = cfg.report.brand_color

    # --- detect URL vs path in <current> ---
    current_is_url = current.startswith(("http://", "https://"))

    # --- validate output path safety ---
    if output is not None:
        validate_out_path(output)
    if json_out is not None:
        validate_out_path(json_out)

    # Errors handled by @handle_compare_errors
    before = load_or_audit_file(baseline_json)
    if current_is_url:
        rprint(f"[cyan]Fetching live metrics for {current} (strategy={strategy})...[/cyan]")
        cache = None if no_cache else _build_pagespeed_cache()
        after = fetch_url_as_audit(current, strategy=strategy, api_key=api_key, cache=cache)
    else:
        current_path = Path(current)
        if not current_path.exists():
            rprint(f"[red]Error:[/red] current file not found: {current_path}")
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None
        after = load_or_audit_file(current_path)
    comparison = run_comparison(before, after)

    # --- pretty table + summary (extracted helpers, identical output) ---
    print_comparison_table(comparison, console=console)
    print_comparison_summary(comparison)

    # --- optional HTML report ---
    if output:
        # Render the current audit with the comparison section attached.
        current_payload = json.loads(after.model_dump_json())
        # The source file is only meaningful for file-based inputs; URLs use
        # the URL itself so the report footer doesn't show a stale tmpfile.
        if current_is_url:
            current_payload["_source_file"] = current
        else:
            current_payload["_source_file"] = current
        from audit.report import _parse_brand_color, _read_brand_logo

        validated_color = _parse_brand_color(brand_color) if brand_color else None
        validated_logo = _read_brand_logo(brand_logo) if brand_logo else None
        if brand_color and validated_color is None:
            rprint(f"[yellow]Warning:[/yellow] Ignoring invalid --brand-color {brand_color!r}.")
        if brand_logo and validated_logo is None:
            rprint(f"[yellow]Warning:[/yellow] Could not read --brand-logo {brand_logo!r}.")
        html = generate_html_report(
            current_payload,
            comparison=comparison,
            brand_logo=validated_logo,
            brand_color=validated_color,
        )
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        if pdf:
            # Render HTML -> PDF via WeasyPrint. The CLI's --pdf flag
            # toggles between the two output formats; the output file
            # extension is the user's choice (no auto-rename here).
            from audit.report import render_pdf_report

            render_pdf_report(html, output)
            rprint(f"\n[green]PDF report written to {output}[/green]")
        else:
            Path(output).write_text(html, encoding="utf-8")
            rprint(f"\n[green]HTML report written to {output}[/green]")
    else:
        print(json.dumps(comparison.model_dump(), indent=2))

    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(comparison.model_dump_json(indent=2), encoding="utf-8")
        rprint(f"[green]Comparison JSON written to {json_out}[/green]")

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# version (convenience, not in spec but harmless)
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print tool version."""
    rprint(f"shopify-image-audit {_VERSION}")


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------


@app.command()
def schedule(
    subcommand: str = typer.Argument(..., help="Subcommand: 'list', 'add', 'remove', or 'run-all'."),
    shop_domain: str = typer.Argument(
        None,
        help="[add/remove] Store hostname, e.g. 'mystore.myshopify.com'.",
    ),
    url: str = typer.Argument(
        None,
        help="[add] Store URL to audit (https://...).",
    ),
    schedule_dir: Path | None = typer.Option(
        None,
        "--schedule-dir",
        help="Override the schedule config directory (default: $XDG_DATA_HOME/.shopify-image-audit/).",
    ),
    history_dir: Path | None = typer.Option(
        None,
        "--history-dir",
        help="[run-all] Override the audit-history directory.",
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        help="[add] Device: mobile or desktop (default: config or mobile).",
    ),
    label: str | None = typer.Option(
        None,
        "--label",
        help="[add] Optional label for the schedule (e.g. 'Daily 09:00').",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="PAGESPEED_API_KEY",
        help="[run-all] Google Cloud API key for PageSpeed (optional, or set PAGESPEED_API_KEY).",
    ),
    parallel: int | None = typer.Option(
        None,
        "--parallel",
        help="[run-all] Number of concurrent store audits. 0 = unlimited (default: config or 1).",
    ),
    stop_on_error: bool = typer.Option(
        False,
        "--stop-on-error",
        help="[run-all] Abort on the first store failure (default: continue past failures).",
    ),
) -> None:
    """Manage scheduled re-audits and run them on demand.

    Scheduling itself (when to run) is delegated to cron / systemd — see
    ``docs/runbook/scheduled_reaudit.md`` for a crontab example. This
    command handles the 'what to run' half: persisting the schedule list
    and executing it via ``run-all``.
    """
    # --- resolve config defaults (flag > env > config > default) ---
    cfg = _cfg()
    if device is None:
        device = cfg.defaults.device
    if history_dir is None and cfg.history.history_dir is not None:
        history_dir = Path(cfg.history.history_dir)
    if api_key is None:
        api_key = cfg.pagespeed.api_key
    # `parallel == 0` is a valid "unlimited" value — never `or`-coalesce it.
    if parallel is None:
        parallel = cfg.defaults.parallel

    if subcommand not in ("list", "add", "remove", "run-all"):
        rprint(
            f"[red]Error:[/red] Unknown schedule subcommand: {subcommand!r} "
            f"(use 'list', 'add', 'remove', or 'run-all')."
            f"{format_suggestion(subcommand, ['list', 'add', 'remove', 'run-all'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if device not in ("mobile", "desktop"):
        rprint(
            f"[red]Error:[/red] --device must be 'mobile' or 'desktop', "
            f"got '{device}'.{format_suggestion(device, ['mobile', 'desktop'])}"
        )
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    from engine.scheduler import ScheduleConfig, ScheduleStore, run_all_schedules

    store_dir = schedule_dir or _default_schedule_dir()
    store = ScheduleStore(store_dir)

    if subcommand == "list":
        schedules = store.load()
        if not schedules:
            rprint(f"[yellow]No schedules configured in {store.path}.[/yellow]")
            rprint("  Use `audit schedule add <shop_domain> <url>` to add one.")
        else:
            _schedule_list(schedules)
    elif subcommand == "add":
        if not shop_domain or not url:
            rprint("[red]Error:[/red] `audit schedule add` requires <shop_domain> and <url>.")
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None
        config = ScheduleConfig(
            shop_domain=shop_domain,
            url=url,
            device=device,
            label=label,
        )
        store.add(config)
        rprint(f"[green]Schedule added:[/green] {shop_domain} -> {url}")
    elif subcommand == "remove":
        if not shop_domain:
            rprint("[red]Error:[/red] `audit schedule remove` requires <shop_domain>.")
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None
        remaining = store.remove(shop_domain)
        if len(remaining) == len(store.load()) + 1:
            rprint(f"[yellow]No schedule found for {shop_domain!r}.[/yellow]")
        else:
            rprint(f"[green]Schedule removed:[/green] {shop_domain}")
    else:  # run-all
        if parallel < 0:
            rprint(f"[red]Error:[/red] --parallel must be >= 0, got {parallel}.")
            rprint(f"{format_suggestion(str(parallel), ['0', '1', '2'])}")
            raise typer.Exit(code=EXIT_INVALID_ARGS) from None

        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        history_store = HistoryStore(base_dir=history_dir)
        schedules = store.load()
        if not schedules:
            rprint(f"[yellow]No schedules to run in {store.path}.[/yellow]")
            raise typer.Exit(code=EXIT_OK) from None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("schedule run-all", total=len(schedules))

            def _on_done(sched: object, _result: object) -> None:
                progress.update(
                    task_id,
                    advance=1,
                    description=getattr(sched, "shop_domain", ""),
                )

            results = run_all_schedules(
                store,
                history_store=history_store,
                api_key=api_key,
                parallel=parallel,
                stop_on_error=stop_on_error,
                on_done=_on_done,
            )
        for r in results:
            if r.success:
                rprint(f"  [green]✓[/green] {r.shop_domain}: recorded (id={r.entry_id})")
            else:
                rprint(f"  [red]✗[/red] {r.shop_domain}: {r.error}")
        if not any(r.success for r in results):
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None

    raise typer.Exit(code=EXIT_OK) from None


def _default_schedule_dir() -> Path:
    """Default schedule config dir (sibling of the history dir)."""
    from engine.history import _default_history_dir

    return _default_history_dir().parent


def _build_pagespeed_cache() -> ResponseCache | None:
    """Construct the default on-disk PageSpeed response cache.

    Returns ``None`` when caching is disabled (``PAGESPEED_CACHE_TTL=0``).
    """
    cache = ResponseCache()
    return cache if cache.ttl > 0 else None


def _schedule_list(schedules: list[Any]) -> None:
    """Print a Rich table of configured schedules."""
    from rich.table import Table

    table = Table(title="Scheduled Re-audits")
    table.add_column("Shop domain")
    table.add_column("URL")
    table.add_column("Device")
    table.add_column("Label")
    for s in schedules:
        table.add_row(s.shop_domain, s.url, s.device, s.label or "—")
    console = Console()
    console.print(table)


# ---------------------------------------------------------------------------
# entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    from engine._logging import configure

    configure()
    app()


if __name__ == "__main__":
    main()
