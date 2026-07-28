"""HTML report generation for audit results.

The report is assembled by focused, single-purpose render functions
(``_render_*``). ``generate_html_report`` is the public entry point and keeps
its original signature/contract so callers (CLI, tests) are unaffected.

A ``_render_comparison_section`` hook is reserved for before/after reporting
(Sprint 2, issue #20 / depends on #18). It currently renders nothing; its shape
will be finalised once the comparison data contract from #18 is ready.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Web Vitals thresholds
# ---------------------------------------------------------------------------

# good <= thresholds[0], poor > thresholds[1], else "needs-improvement".
# Values mirror the previous inline table (LCP/CLS/INP/TTFB in native units).
_VITALS_THRESHOLDS: dict[str, tuple[float, float]] = {
    "lcp_ms": (2500, 4000),
    "cls": (0.1, 0.25),
    "inp_ms": (200, 500),
    "ttfb_ms": (800, 1800),
}


def _vitals_status(metric: str, value: float) -> str:
    """Return good/needs-improvement/poor based on Web Vitals thresholds."""
    good, poor = _VITALS_THRESHOLDS.get(metric, (0, float("inf")))
    if value <= good:
        return "good"
    elif value <= poor:
        return "needs-improvement"
    return "poor"


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------

def _aggregate_stats(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics for the stats grid."""
    total_images = len(images)
    total_bytes = sum(img["bytes"] for img in images)
    total_waste = sum(img.get("waste_bytes_est", 0) for img in images)
    avg_score = sum(img["score"] for img in images) / total_images if total_images > 0 else 0
    role_counts: dict[str, int] = {}
    for img in images:
        role = img["role"]
        role_counts[role] = role_counts.get(role, 0) + 1
    return {
        "total_images": total_images,
        "total_bytes": total_bytes,
        "total_waste": total_waste,
        "avg_score": avg_score,
        "role_counts": role_counts,
    }


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

_CSS = """        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        h1 {
            font-size: 2em;
            margin-bottom: 10px;
            color: #1a1a1a;
        }
        h2 {
            font-size: 1.5em;
            margin-top: 30px;
            margin-bottom: 15px;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }
        h3 {
            font-size: 1.2em;
            margin-top: 20px;
            margin-bottom: 10px;
            color: #34495e;
        }
        .meta {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .meta p {
            margin: 5px 0;
        }
        .meta strong {
            color: #2c3e50;
        }
        .vitals {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .vital-card {
            background: white;
            border: 2px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            text-align: center;
        }
        .vital-card.good { border-color: #27ae60; }
        .vital-card.needs-improvement { border-color: #f39c12; }
        .vital-card.poor { border-color: #e74c3c; }
        .vital-name {
            font-size: 0.9em;
            color: #7f8c8d;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .vital-value {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        .vital-card.good .vital-value { color: #27ae60; }
        .vital-card.needs-improvement .vital-value { color: #f39c12; }
        .vital-card.poor .vital-value { color: #e74c3c; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-box {
            background: #3498db;
            color: white;
            padding: 20px;
            border-radius: 5px;
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
        }
        .stat-label {
            font-size: 0.9em;
            opacity: 0.9;
            margin-top: 5px;
        }
        .issues {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 15px 0;
        }
        .issues ul {
            margin-left: 20px;
            margin-top: 10px;
        }
        .issues li {
            margin: 5px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #34495e;
            color: white;
            font-weight: 600;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .score {
            font-weight: bold;
            padding: 4px 8px;
            border-radius: 3px;
        }
        .score.high { background: #d4edda; color: #155724; }
        .score.medium { background: #fff3cd; color: #856404; }
        .score.low { background: #f8d7da; color: #721c24; }
        .role {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: 500;
        }
        .role.hero { background: #e8f5e9; color: #2e7d32; }
        .role.above_fold { background: #e3f2fd; color: #1565c0; }
        .role.product_primary { background: #f3e5f5; color: #6a1b9a; }
        .role.product_secondary { background: #fff3e0; color: #e65100; }
        .role.decorative { background: #fce4ec; color: #c2185b; }
        .role.unknown { background: #eceff1; color: #455a64; }
        .bytes {
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }
        .lcp-badge {
            display: inline-block;
            background: #ff9800;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.75em;
            font-weight: bold;
        }
        .recommendation {
            font-size: 0.9em;
            color: #555;
            font-style: italic;
        }
        footer {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }
        /* Reserved styling for the before/after comparison section (#20). */
        .comparison {
            margin: 20px 0;
        }"""


def _render_head() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shopify Image Audit Report</title>
    <style>
{_CSS}
    </style>
</head>
<body>
    <div class="container">
        <h1>🖼️ Shopify Image Audit Report</h1>

"""


def _render_meta(meta: dict[str, Any]) -> str:
    notes_line = (
        f"<p><strong>Notes:</strong> {escape(meta.get('notes', 'N/A'))}</p>"
        if meta.get("notes") else ""
    )
    return f"""        <div class="meta">
            <p><strong>URL:</strong> {escape(meta['url'])}</p>
            <p><strong>Timestamp:</strong> {escape(meta['timestamp_utc'])}</p>
            <p><strong>Device:</strong> {escape(meta['device']).capitalize()}</p>
            <p><strong>Runs:</strong> {meta['runs']}</p>
            <p><strong>Tool:</strong> {escape(meta['tool']).capitalize()}</p>
            {notes_line}
        </div>

"""


def _render_vital_card(name: str, metric: str, value: float, fmt: str) -> str:
    status = _vitals_status(metric, value)
    status_label = status.replace("_", " ").title()
    return f"""            <div class="vital-card {status}">
                <div class="vital-name">{name}</div>
                <div class="vital-value">{fmt.format(value)}</div>
                <div class="vital-status">{status_label}</div>
            </div>"""


def _render_vitals(vitals: dict[str, Any]) -> str:
    cards = "\n".join(
        _render_vital_card(name, metric, vitals[metric], fmt)
        for name, metric, fmt in (
            ("LCP", "lcp_ms", "{:.0f}ms"),
            ("CLS", "cls", "{:.3f}"),
            ("INP", "inp_ms", "{:.0f}ms"),
            ("TTFB", "ttfb_ms", "{:.0f}ms"),
        )
    )
    return f"""        <h2>📊 Core Web Vitals</h2>
        <div class="vitals">
{cards}
        </div>

"""


def _render_stats(stats: dict[str, Any]) -> str:
    return f"""        <h2>📈 Image Summary</h2>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value">{stats['total_images']}</div>
                <div class="stat-label">Total Images</div>
            </div>
            <div class="stat-box" style="background: #9b59b6;">
                <div class="stat-value">{stats['total_bytes'] / 1024 / 1024:.2f} MB</div>
                <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-box" style="background: #e74c3c;">
                <div class="stat-value">{stats['total_waste'] / 1024:.0f} KB</div>
                <div class="stat-label">Est. Waste</div>
            </div>
            <div class="stat-box" style="background: #27ae60;">
                <div class="stat-value">{stats['avg_score']:.0f}</div>
                <div class="stat-label">Avg Score</div>
            </div>
        </div>

"""


def _render_issues(summary: dict[str, Any]) -> str:
    if not summary["top_issues"]:
        return ""
    items = "".join(f"<li>{escape(issue)}</li>" for issue in summary["top_issues"])
    return f"""        <div class="issues">
            <h3>⚠️ Top Issues</h3>
            <ul>
                {items}
            </ul>
        </div>

"""


def _render_comparison_section(audit_result: dict[str, Any]) -> str:
    """Render the before/after comparison section.

    Reserved for Sprint 2 before/after reporting (issue #20). Returns an empty
    string until the comparison data contract is finalised in #18. When
    comparison data becomes available it will be read from a well-known key
    (TBD with #18) and rendered here; do not lock the shape prematurely.
    """
    return ""


def _render_image_row(img: dict[str, Any]) -> str:
    score_class = "high" if img["score"] >= 75 else "medium" if img["score"] >= 50 else "low"
    src_display = img["src"][-50:] if len(img["src"]) > 50 else img["src"]

    displayed = f"{img.get('displayed_width', 'N/A')}×{img.get('displayed_height', 'N/A')}"
    natural = f"{img.get('natural_width', 'N/A')}×{img.get('natural_height', 'N/A')}"
    dimensions = f"{displayed}<br><small style='color:#888;'>({natural})</small>"

    lcp_badge = '<span class="lcp-badge">LCP</span> ' if img.get("is_lcp_candidate") else ""

    return f"""                <tr>
                    <td class="bytes" title="{escape(img['src'])}">{lcp_badge}{escape(src_display)}</td>
                    <td><span class="role {escape(img['role'])}">{escape(img['role'].replace('_', ' '))}</span></td>
                    <td><span class="score {score_class}">{img['score']}</span></td>
                    <td class="bytes">{img['bytes'] / 1024:.1f} KB</td>
                    <td>{dimensions}</td>
                    <td class="bytes">{img.get('waste_bytes_est', 0) / 1024:.1f} KB</td>
                    <td class="recommendation">{escape(img.get('recommendation', '—'))}</td>
                </tr>
"""


def _render_image_table(images: list[dict[str, Any]]) -> str:
    rows = "".join(_render_image_row(img) for img in images)
    return f"""        <h2>🖼️ Image Details</h2>
        <table>
            <thead>
                <tr>
                    <th>Source</th>
                    <th>Role</th>
                    <th>Score</th>
                    <th>Size</th>
                    <th>Dimensions</th>
                    <th>Waste</th>
                    <th>Recommendation</th>
                </tr>
            </thead>
            <tbody>
{rows}            </tbody>
        </table>

"""


def _render_role_distribution(role_counts: dict[str, int]) -> str:
    lines = ""
    for role, count in sorted(role_counts.items()):
        role_escaped = escape(role)
        role_display = escape(role.replace("_", " "))
        suffix = "s" if count != 1 else ""
        line = f'<li><span class="role {role_escaped}">{role_display}</span>: {count} image{suffix}</li>'
        lines += f"            {line}\n"
    return f"""        <h2>📋 Role Distribution</h2>
        <ul>
{lines}        </ul>
"""


def _render_footer(audit_result: dict[str, Any]) -> str:
    source_name = Path(audit_result.get("_source_file", "audit_result.json")).name
    return f"""
        <footer>
            <p>Generated by shopify-image-audit v0.1</p>
            <p>Report generated from: {escape(source_name)}</p>
        </footer>
    </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_report(audit_result: dict[str, Any]) -> str:
    """
    Generate an HTML report from an audit result dictionary.

    Args:
        audit_result: Validated audit result dictionary matching the schema

    Returns:
        HTML string ready to be written to a file
    """
    # Accept a plain scored-image list in addition to the full AuditResult envelope.
    if isinstance(audit_result, list):
        audit_result = {
            "meta": {
                "url": "N/A",
                "timestamp_utc": "N/A",
                "device": "unknown",
                "runs": 1,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 0, "cls": 0, "inp_ms": 0, "ttfb_ms": 0},
            "images": audit_result,
            "summary": {"top_issues": []},
        }

    meta = audit_result["meta"]
    vitals = audit_result["vitals"]
    images = audit_result["images"]
    summary = audit_result["summary"]
    stats = _aggregate_stats(images)

    html = _render_head()
    html += _render_meta(meta)
    html += _render_vitals(vitals)
    html += _render_stats(stats)
    html += _render_issues(summary)
    html += _render_comparison_section(audit_result)
    html += _render_image_table(images)
    html += _render_role_distribution(stats["role_counts"])
    html += _render_footer(audit_result)

    return html


def write_html_report(audit_result_path: Path, output_path: Path) -> None:
    """
    Read an audit result JSON file and write an HTML report.

    Args:
        audit_result_path: Path to the audit_result.json file
        output_path: Path where the HTML report should be written

    Raises:
        FileNotFoundError: If audit_result_path doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
        KeyError: If required fields are missing from the audit result
    """
    with open(audit_result_path, encoding="utf-8") as f:
        audit_result = json.load(f)

    # Store source file for footer reference
    if isinstance(audit_result, dict):
        audit_result["_source_file"] = str(audit_result_path)

    html_content = generate_html_report(audit_result)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
