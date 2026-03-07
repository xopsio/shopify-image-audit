"""
Typer-based CLI for Shopify Image Audit.

Commands
--------
audit            – Run the full audit pipeline on a Lighthouse JSON / fixture.
validate-schema  – Validate an existing JSON file against the schema.
render-html      – (stub) Render an audit result to HTML.
version          – Print tool version.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from audit.models import AuditResult
from engine.audit_orchestrator import run_audit

app = typer.Typer(
    name="shopify-image-audit",
    help="Shopify store image audit – Lighthouse-based analysis with heuristic and ML scoring.",
    add_completion=False,
)

_VERSION = "0.1.0"

console = Console()

# ---- repo-level paths ----
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "audit_result.schema.json"


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

@app.command()
def audit(
    url: Optional[str] = typer.Argument(None, help="Shopify store URL to audit (requires Lighthouse)."),
    lhr: Optional[Path] = typer.Option(None, "--lhr", help="Path to an existing Lighthouse JSON report or fixture."),
    device: str = typer.Option("mobile", "--device", help="Device type: mobile or desktop."),
    runs: int = typer.Option(1, "--runs", help="Number of Lighthouse runs."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Write JSON result to this file."),
) -> None:
    """Run the full image audit pipeline."""
    if lhr is None and url is None:
        rprint("[red]Error:[/red] Provide either a URL or --lhr <path>.")
        raise typer.Exit(code=1)

    if lhr is not None:
        json_path = lhr
    else:
        # Lighthouse live run (placeholder – requires lighthouse_runner)
        rprint(f"[yellow]Live Lighthouse run for {url} is not yet implemented.[/yellow]")
        rprint("[yellow]Please provide --lhr with a pre-existing report.[/yellow]")
        raise typer.Exit(code=1)

    if not json_path.exists():
        rprint(f"[red]File not found:[/red] {json_path}")
        raise typer.Exit(code=1)

    result: AuditResult = run_audit(json_path, url=url, device=device, runs=runs)

    # pretty table
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

    # write to file
    if output:
        output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        rprint(f"\n[green]Result written to {output}[/green]")


# ---------------------------------------------------------------------------
# validate-schema
# ---------------------------------------------------------------------------

@app.command("validate-schema")
def validate_schema(
    path: Path = typer.Argument(..., help="Path to a JSON file to validate against the audit schema."),
) -> None:
    """Validate a JSON file against audit_result.schema.json using Pydantic."""
    if not path.exists():
        rprint(f"[red]File not found:[/red] {path}")
        raise typer.Exit(code=1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    try:
        AuditResult.model_validate(data)
        rprint(f"[green]OK: {path} is valid.[/green]")
    except Exception as exc:
        rprint(f"[red]FAIL: Validation failed:[/red]\n{exc}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# render-html (stub)
# ---------------------------------------------------------------------------

@app.command("render-html")
def render_html(
    path: Path = typer.Argument(..., help="Path to audit result JSON."),
    output: Path = typer.Option("report.html", "-o", "--output", help="Output HTML file."),
) -> None:
    """Render an audit result JSON to an HTML report (stub)."""
    rprint("[yellow]HTML rendering is not yet implemented.[/yellow]")
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# version
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

