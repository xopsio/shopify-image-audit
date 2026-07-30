"""
Rich table renderers for CLI output.

Extracted from ``cli.py`` so the command bodies stay declarative. Each
function takes the data it needs and prints via the provided ``Console``.

Behaviour-preserving refactor: output strings are identical to the previous
inline implementations. The only change is column structure; visual output
must remain the same.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from audit.models import AuditResult, ComparisonResult

# Mapping (label, comparison.vitals attr key, format string) for the per-vital row.
_VITAL_ROWS = (
    ("LCP", "lcp", "{:.0f}ms"),
    ("CLS", "cls", "{:.3f}"),
    ("INP", "inp", "{:.0f}ms"),
    ("TTFB", "ttfb", "{:.0f}ms"),
)

_STATUS_COLOUR = {
    "improved": "green",
    "regressed": "red",
    "unchanged": "dim",
}


def print_audit_results(result: AuditResult, *, console: Console) -> None:
    """Render the per-image results table for ``audit run`` output."""
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


def print_comparison_table(comparison: ComparisonResult, *, console: Console) -> None:
    """Render the before/after vitals delta table for ``audit compare`` output."""
    table = Table(title="Before / After Comparison")
    table.add_column("Metric", style="cyan")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Δ", justify="right")

    for label, key, fmt in _VITAL_ROWS:
        delta = getattr(comparison.vitals, key)
        sign = "+" if delta.delta > 0 else ""
        colour = _STATUS_COLOUR.get(delta.status, "dim")
        table.add_row(
            label,
            fmt.format(delta.before),
            fmt.format(delta.after),
            f"[{colour}]{sign}{fmt.format(delta.delta)}[/{colour}]",
        )

    console.print(table)


def print_comparison_summary(comparison: ComparisonResult) -> None:
    """Print the text summary (improvements, regressions, ROI) after the table.

    Uses ``rich.print`` for the coloured labels. Kept separate from the
    table because it's text rather than a structured grid.
    """
    from rich import print as rprint

    rprint("\n[bold]Improvements:[/bold]")
    for item in comparison.summary.top_improvements:
        rprint(f"  [green]✓[/green] {item}")
    if comparison.summary.top_regressions:
        rprint("\n[bold]Regressions:[/bold]")
        for item in comparison.summary.top_regressions:
            rprint(f"  [red]✗[/red] {item}")
    rprint(f"\n[blue]ROI:[/blue] {comparison.summary.roi_estimate}")


def print_audit_summary(result: AuditResult) -> None:
    """Print the text summary (top issues) after the audit results table."""
    from rich import print as rprint

    rprint("\n[bold]Summary:[/bold]")
    for issue in result.summary.top_issues:
        rprint(f"  - {issue}")
