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
    0  – success
    2  – invalid arguments
    10 – lighthouse failure
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from audit.models import AuditResult
from audit.report import write_html_report
from engine.audit_orchestrator import run_audit

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
# Top-level app – NO nested "audit" group so that `audit run …` works
# directly from the console-script named ``audit``.
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="audit",
    help="Shopify store image audit – Lighthouse-based analysis with heuristic and ML scoring.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Lighthouse helper
# ---------------------------------------------------------------------------

def _run_lighthouse(
    url: str,
    *,
    device: str,
    runs: int,
    out_dir: Path,
) -> Path:
    """Run Lighthouse CLI and return the path to the best JSON report.

    Raises ``typer.Exit(code=10)`` on failure.
    """
    lh_bin = shutil.which("lighthouse")
    if lh_bin is None:
        rprint("[red]Error:[/red] `lighthouse` CLI not found on PATH. Install with: npm i -g lighthouse")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE)

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
        rprint(f"[cyan]Lighthouse run {i}/{runs}…[/cyan]")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            rprint(f"[red]Lighthouse failed (run {i}):[/red] {exc.stderr[:500]}")
            raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE)
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
    lhr: Optional[Path] = typer.Option(None, "--lhr", help="Use an existing Lighthouse JSON instead of running live."),
) -> None:
    """Run Lighthouse audit on <url>, analyse images, and write results."""
    # --- validate URL scheme ---
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ("http", "https"):
        scheme_display = parsed_url.scheme or "(empty)"
        rprint(f"[red]Error:[/red] URL scheme must be http or https, got '{scheme_display}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    # --- validate --out-dir safety ---
    out_dir_p = Path(out_dir)
    if out_dir_p.is_absolute():
        rprint("[red]Error:[/red] --out-dir must be a relative path.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)
    if ".." in out_dir_p.parts:
        rprint("[red]Error:[/red] --out-dir must not contain '..' segments.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)
    # Resolve and check containment using pathlib's safe relative_to()
    resolved_out = Path.cwd().joinpath(out_dir_p).resolve()
    cwd_resolved = Path.cwd().resolve()

    try:
        resolved_out.relative_to(cwd_resolved)
    except ValueError:
        rprint("[red]Error:[/red] --out-dir resolves outside the working directory.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    # --- validate args ---
    if device not in ("mobile", "desktop"):
        rprint(f"[red]Error:[/red] --device must be 'mobile' or 'desktop', got '{device}'.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    if runs < 1:
        rprint("[red]Error:[/red] --runs must be >= 1.")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    # --- obtain LHR JSON ---
    if lhr is not None:
        if not lhr.exists():
            rprint(f"[red]Error:[/red] File not found: {lhr}")
            raise typer.Exit(code=EXIT_INVALID_ARGS)
        json_path = lhr
    else:
        json_path = _run_lighthouse(url, device=device, runs=runs, out_dir=out_dir)

    # --- run the audit pipeline ---
    try:
        result: AuditResult = run_audit(json_path, url=url, device=device, runs=runs)
    except Exception as exc:
        rprint(f"[red]Audit pipeline error:[/red] {exc}")
        raise typer.Exit(code=EXIT_LIGHTHOUSE_FAILURE)

    # --- pretty table ---
    table = Table(title="Image Audit Results")
    table.add_column("src", style="cyan", no_wrap=False, max_width=60)
    table.add_column("role", style="magenta")
    table.add_column("score", justify="right")
    table.add_column("bytes", justify="right")
    table.add_column("LCP?", justify="center")
    table.add_column("recommendation", style="dim", no_wrap=False, max_width=50)

    for img in result.images:
        table.add_row(
            img.src,
            img.role.value,
            str(img.score),
            f"{img.bytes:,}",
            "Y" if img.is_lcp_candidate else "",
            img.recommendation or "",
        )

    console.print(table)

    # summary
    rprint("\n[bold]Summary:[/bold]")
    for issue in result.summary.top_issues:
        rprint(f"  - {issue}")

    # --- write JSON result ---
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    result_file = out_dir_path / "audit_result.json"
    result_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    rprint(f"\n[green]Result written to {result_file}[/green]")

    raise typer.Exit(code=EXIT_OK)


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
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    from audit.parser import parse

    try:
        with open(lighthouse_json, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {lighthouse_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    try:
        images = parse(raw)
        rprint(json.dumps(images, indent=2))
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to parse Lighthouse data: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    raise typer.Exit(code=EXIT_OK)


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

@app.command()
def score(
    audit_input_json: Path = typer.Argument(..., help="Path to intermediate audit input JSON."),
) -> None:
    """Assign role, score (0-100), and recommendations to each image."""
    if not audit_input_json.exists():
        rprint(f"[red]Error:[/red] File not found: {audit_input_json}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    from audit.ranker_heuristic import rank

    try:
        with open(audit_input_json, encoding="utf-8") as f:
            images = json.load(f)
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {audit_input_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    try:
        scored = rank(images)
        rprint(json.dumps(scored, indent=2))
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to score images: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    raise typer.Exit(code=EXIT_OK)


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
        raise typer.Exit(code=EXIT_INVALID_ARGS)

    try:
        write_html_report(audit_result_json, output)
        rprint(f"[green]✓[/green] HTML report written to: {output}")
    except json.JSONDecodeError as e:
        rprint(f"[red]Error:[/red] Invalid JSON in {audit_result_json}: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)
    except KeyError as e:
        rprint(f"[red]Error:[/red] Missing required field in audit result: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)
    except Exception as e:
        rprint(f"[red]Error:[/red] Failed to generate report: {e}")
        raise typer.Exit(code=EXIT_INVALID_ARGS)


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

