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
import shutil
import subprocess
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console

from audit.models import AuditResult
from audit.report import generate_html_report, write_html_report
from core.baseline_manager import compare as run_comparison
from core.baseline_manager import save_baseline
from engine.audit_orchestrator import run_audit
from engine.cli_helpers._dispatchers import fetch_url_as_audit, load_or_audit_file
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
from integrations.pagespeed_api import PageSpeedAPIClient

# --- Exit codes per spec ---------------------------------------------------
EXIT_OK = 0
EXIT_INVALID_ARGS = 2
EXIT_LIGHTHOUSE_FAILURE = 10

_VERSION = "0.1.0"

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


# ---------------------------------------------------------------------------
# Lighthouse helper (kept inline — requires subprocess + external CLI)
# ---------------------------------------------------------------------------

def _run_lighthouse(
    url: str,
    *,
    device: str,
    runs: int,
    out_dir: Path,
) -> Path:
    """Run Lighthouse CLI and return the path to the best JSON report.

    Raises ``typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE)`` on failure.
    """
    lh_bin = shutil.which("lighthouse")
    if lh_bin is None:
        rprint("[red]Error:[/red] `lighthouse` CLI not found on PATH. Install with: npm i -g lighthouse")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None

    out_dir.mkdir(parents=True, exist_ok=True)

    form_factor = "desktop" if device == "desktop" else "mobile"
    emulated = "none" if device == "desktop" else "mobile"

    best_path: Path | None = None
    for i in range(1, runs + 1):
        out_file = out_dir / f"lhr_run{i}.json"
        cmd = [
            lh_bin,
            url,
            "--output=json",
            f"--output-path={out_file}",
            f"--preset={form_factor}",
            f"--emulated-form-factor={emulated}",
            "--only-categories=performance",
            "--chrome-flags=--headless",
        ]
        rprint(f"[cyan]Lighthouse run {i}/{runs}[/cyan]")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            rprint(f"[red]Lighthouse failed (run {i}):[/red] {exc.stderr[:500]}")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from exc
        best_path = out_file  # simple: use the last successful run

    assert best_path is not None
    return best_path


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command()
def run(
    url: str = typer.Argument(..., help="Shopify store URL to audit."),
    device: str = typer.Option("mobile", "--device", help="Device type: mobile or desktop."),
    runs: int = typer.Option(3, "--runs", help="Number of Lighthouse runs (default 3)."),
    out_dir: Path = typer.Option("artifacts", "--out-dir", help="Directory for output artifacts."),
    lhr: Path | None = typer.Option(None, "--lhr", help="Use an existing Lighthouse JSON instead of running live."),
) -> None:
    """Run Lighthouse audit on <url>, analyse images, and write results."""
    # --- validate URL scheme ---
    validate_run_url(url)

    # --- validate --out-dir safety ---
    validate_out_path(out_dir, label="--out-dir")

    # --- validate args ---
    if device not in ("mobile", "desktop"):
        rprint(f"[red]Error:[/red] --device must be 'mobile' or 'desktop', got '{device}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if runs < 1:
        rprint("[red]Error:[/red] --runs must be >= 1.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- obtain LHR JSON ---
    if lhr is not None:
        json_path: Path = require_exists(lhr)
    else:
        json_path = _run_lighthouse(url, device=device, runs=runs, out_dir=out_dir)

    # --- run the audit pipeline ---
    try:
        result: AuditResult = run_audit(json_path, url=url, device=device, runs=runs)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc
    except ValueError as exc:
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc
    except Exception as exc:
        # Other errors (e.g., schema validation) are Lighthouse-related
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from exc

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
    strategy: str = typer.Option("mobile", "--strategy", help="Strategy: mobile or desktop (default: mobile)."),
    api_key: str | None = typer.Option(None, "--api-key", help="Google Cloud API key (optional)."),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output JSON file (default: print to stdout)."),
) -> None:
    """Fetch live performance metrics from Google PageSpeed Insights API."""
    # --- validate URL (allow scheme-less for normalization by API) ---
    validate_measure_url(url)

    # --- validate strategy ---
    if strategy not in ("mobile", "desktop"):
        rprint(f"[red]Error:[/red] --strategy must be 'mobile' or 'desktop', got '{strategy}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- validate output path safety ---
    if output is not None:
        validate_out_path(output)

    # --- fetch metrics ---
    try:
        client = PageSpeedAPIClient(api_key=api_key)
        metrics = client.get_metrics(url, strategy=strategy)
    except ValueError as exc:
        rprint(f"[red]Error:[/red] Invalid input: {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except RuntimeError as exc:
        rprint(f"[red]Error:[/red] PageSpeed API error: {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None
    except Exception as exc:
        rprint(f"[red]Error:[/red] Failed to fetch metrics: {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None

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
# extract
# ---------------------------------------------------------------------------

@app.command()
def extract(
    lighthouse_json: Path = typer.Argument(..., help="Path to a Lighthouse JSON report."),
) -> None:
    """Extract image + LCP-related features into an intermediate JSON."""
    if not lighthouse_json.exists():
        rprint(f"[red]Error:[/red] File not found: {lighthouse_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    from audit.parser import parse

    try:
        with open(lighthouse_json, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {lighthouse_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    try:
        images = parse(raw)
        print(json.dumps(images, indent=2))
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to parse Lighthouse data: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

@app.command()
def score(
    audit_input_json: Path = typer.Argument(..., help="Path to intermediate audit input JSON."),
    ranker: str = typer.Option("heuristic", "--ranker",
                                help="Scoring algorithm: 'heuristic' (default) or 'ml'."),
) -> None:
    """Assign role, score (0-100), and recommendations to each image."""
    if not audit_input_json.exists():
        rprint(f"[red]Error:[/red] File not found: {audit_input_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if ranker not in ("heuristic", "ml"):
        rprint(f"[red]Error:[/red] --ranker must be 'heuristic' or 'ml', got '{ranker}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if ranker == "ml":
        from audit.ranker_ml import rank
    else:
        from audit.ranker_heuristic import rank

    try:
        with open(audit_input_json, encoding="utf-8") as f:
            images = json.load(f)
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {audit_input_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    try:
        scored = rank(images)
        print(json.dumps(scored, indent=2))
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to score images: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@app.command()
def report(
    audit_result_json: Path = typer.Argument(..., help="Path to audit_result.json."),
    output: Path = typer.Option("report.html", "-o", "--output", help="Output HTML file."),
) -> None:
    """Render an audit result JSON to an HTML report."""
    if not audit_result_json.exists():
        rprint(f"[red]Error:[/red] File not found: {audit_result_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    try:
        write_html_report(audit_result_json, output)
        rprint(f"[green]OK[/green] HTML report written to: {output}")
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {audit_result_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except KeyError as e:
        rprint(f"[red]Error:[/red] Missing required field in audit result: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to generate report: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------

@app.command()
def baseline(
    lhr_json: Path = typer.Argument(..., help="Path to a Lighthouse JSON / fixture report to use as the baseline."),
    save: Path = typer.Option(..., "--save", help="Where to write the baseline audit_result.json."),
    url: str | None = typer.Option(None, "--url", help="Override the store URL in the baseline meta."),
    device: str = typer.Option("mobile", "--device", help="Device type: mobile or desktop."),
) -> None:
    """Run an audit on <lhr_json> and store it as a reusable baseline."""
    if not lhr_json.exists():
        rprint(f"[red]Error:[/red] File not found: {lhr_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    if device not in ("mobile", "desktop"):
        rprint(f"[red]Error:[/red] --device must be 'mobile' or 'desktop', got '{device}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None

    # --- validate --save path safety ---
    validate_out_path(save)

    try:
        result: AuditResult = run_audit(lhr_json, url=url, device=device)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from None
    except Exception as exc:
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from None

    save_baseline(result, save)
    rprint(f"[green]Baseline saved to {save}[/green]")
    rprint(f"  URL: {result.meta.url} | LCP: {result.vitals.lcp_ms:.0f}ms | "
          f"images: {len(result.images)} | {sum(i.bytes for i in result.images) / 1024:.0f} KB")
    raise typer.Exit(code=EXIT_OK) from None


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

@app.command()
def compare(
    baseline_json: Path = typer.Argument(..., help="Path to a baseline audit_result.json (from `audit baseline`)."),
    current: str = typer.Argument(..., help="Path to the current audit_result.json OR a live URL (https://...)."),
    output: Path | None = typer.Option(None, "-o", "--output",
                                          help="Write an HTML before/after report here (default: stdout JSON)."),
    json_out: Path | None = typer.Option(None, "--json",
                                            help="Also write the comparison result JSON to this file."),
    strategy: str = typer.Option("mobile", "--strategy", help="PageSpeed strategy when <current> is a URL."),
    api_key: str | None = typer.Option(None, "--api-key", help="Google Cloud API key for PageSpeed (optional)."),
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

    # --- detect URL vs path in <current> ---
    current_is_url = current.startswith(("http://", "https://"))

    # --- validate output path safety ---
    if output is not None:
        validate_out_path(output)
    if json_out is not None:
        validate_out_path(json_out)

    try:
        before = load_or_audit_file(baseline_json)
        if current_is_url:
            rprint(f"[cyan]Fetching live metrics for {current} (strategy={strategy})...[/cyan]")
            after = fetch_url_as_audit(current, strategy=strategy, api_key=api_key)
        else:
            current_path = Path(current)
            if not current_path.exists():
                rprint(f"[red]Error:[/red] current file not found: {current_path}")
                raise typer.Exit(code=EXIT_INVALID_ARGS) from None
            after = load_or_audit_file(current_path)
        comparison = run_comparison(before, after)
    except (json.JSONDecodeError, ValueError) as exc:
        rprint(f"[red]Error:[/red] Invalid input: {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc
    except FileNotFoundError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc
    except RuntimeError as exc:
        # Backend failure (PageSpeed API rate limit, 5xx, schema drift).
        rprint(f"[red]Error:[/red] Backend failure: {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE) from exc
    except Exception as exc:
        rprint(f"[red]Error:[/red] Failed to compare audits: {exc}")
        raise typer.Exit(code=EXIT_INVALID_ARGS) from exc

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
        html = generate_html_report(current_payload, comparison=comparison)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
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
# entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    app()


if __name__ == "__main__":
    main()
