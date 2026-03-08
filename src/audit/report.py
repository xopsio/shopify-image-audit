"""HTML report generation for audit results."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def generate_html_report(audit_result: dict[str, Any]) -> str:
    """
    Generate an HTML report from an audit result dictionary.

    Args:
        audit_result: Validated audit result dictionary matching the schema

    Returns:
        HTML string ready to be written to a file
    """
    meta = audit_result["meta"]
    vitals = audit_result["vitals"]
    images = audit_result["images"]
    summary = audit_result["summary"]

    # Calculate aggregate stats
    total_images = len(images)
    total_bytes = sum(img["bytes"] for img in images)
    total_waste = sum(img.get("waste_bytes_est", 0) for img in images)
    avg_score = sum(img["score"] for img in images) / total_images if total_images > 0 else 0

    # Role distribution
    role_counts: dict[str, int] = {}
    for img in images:
        role = img["role"]
        role_counts[role] = role_counts.get(role, 0) + 1

    # Vitals status
    def vitals_status(metric: str, value: float) -> str:
        """Return good/needs-improvement/poor based on Web Vitals thresholds."""
        thresholds = {
            "lcp_ms": (2500, 4000),
            "cls": (0.1, 0.25),
            "inp_ms": (200, 500),
            "ttfb_ms": (800, 1800),
        }
        good, poor = thresholds.get(metric, (0, float("inf")))
        if value <= good:
            return "good"
        elif value <= poor:
            return "needs-improvement"
        else:
            return "poor"

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shopify Image Audit Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            font-size: 2em;
            margin-bottom: 10px;
            color: #1a1a1a;
        }}
        h2 {{
            font-size: 1.5em;
            margin-top: 30px;
            margin-bottom: 15px;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }}
        h3 {{
            font-size: 1.2em;
            margin-top: 20px;
            margin-bottom: 10px;
            color: #34495e;
        }}
        .meta {{
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .meta p {{
            margin: 5px 0;
        }}
        .meta strong {{
            color: #2c3e50;
        }}
        .vitals {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .vital-card {{
            background: white;
            border: 2px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            text-align: center;
        }}
        .vital-card.good {{ border-color: #27ae60; }}
        .vital-card.needs-improvement {{ border-color: #f39c12; }}
        .vital-card.poor {{ border-color: #e74c3c; }}
        .vital-name {{
            font-size: 0.9em;
            color: #7f8c8d;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .vital-value {{
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }}
        .vital-card.good .vital-value {{ color: #27ae60; }}
        .vital-card.needs-improvement .vital-value {{ color: #f39c12; }}
        .vital-card.poor .vital-value {{ color: #e74c3c; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-box {{
            background: #3498db;
            color: white;
            padding: 20px;
            border-radius: 5px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
            margin-top: 5px;
        }}
        .issues {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 15px 0;
        }}
        .issues ul {{
            margin-left: 20px;
            margin-top: 10px;
        }}
        .issues li {{
            margin: 5px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #34495e;
            color: white;
            font-weight: 600;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .score {{
            font-weight: bold;
            padding: 4px 8px;
            border-radius: 3px;
        }}
        .score.high {{ background: #d4edda; color: #155724; }}
        .score.medium {{ background: #fff3cd; color: #856404; }}
        .score.low {{ background: #f8d7da; color: #721c24; }}
        .role {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: 500;
        }}
        .role.hero {{ background: #e8f5e9; color: #2e7d32; }}
        .role.above_fold {{ background: #e3f2fd; color: #1565c0; }}
        .role.product_primary {{ background: #f3e5f5; color: #6a1b9a; }}
        .role.product_secondary {{ background: #fff3e0; color: #e65100; }}
        .role.decorative {{ background: #fce4ec; color: #c2185b; }}
        .role.unknown {{ background: #eceff1; color: #455a64; }}
        .bytes {{
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        .lcp-badge {{
            display: inline-block;
            background: #ff9800;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.75em;
            font-weight: bold;
        }}
        .recommendation {{
            font-size: 0.9em;
            color: #555;
            font-style: italic;
        }}
        footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🖼️ Shopify Image Audit Report</h1>
        
        <div class="meta">
            <p><strong>URL:</strong> {escape(meta['url'])}</p>
            <p><strong>Timestamp:</strong> {escape(meta['timestamp_utc'])}</p>
            <p><strong>Device:</strong> {escape(meta['device']).capitalize()}</p>
            <p><strong>Runs:</strong> {meta['runs']}</p>
            <p><strong>Tool:</strong> {escape(meta['tool']).capitalize()}</p>
            {f"<p><strong>Notes:</strong> {escape(meta.get('notes', 'N/A'))}</p>" if meta.get('notes') else ""}
        </div>

        <h2>📊 Core Web Vitals</h2>
        <div class="vitals">
            <div class="vital-card {vitals_status('lcp_ms', vitals['lcp_ms'])}">
                <div class="vital-name">LCP</div>
                <div class="vital-value">{vitals['lcp_ms']:.0f}ms</div>
                <div class="vital-status">{vitals_status('lcp_ms', vitals['lcp_ms']).replace('_', ' ').title()}</div>
            </div>
            <div class="vital-card {vitals_status('cls', vitals['cls'])}">
                <div class="vital-name">CLS</div>
                <div class="vital-value">{vitals['cls']:.3f}</div>
                <div class="vital-status">{vitals_status('cls', vitals['cls']).replace('_', ' ').title()}</div>
            </div>
            <div class="vital-card {vitals_status('inp_ms', vitals['inp_ms'])}">
                <div class="vital-name">INP</div>
                <div class="vital-value">{vitals['inp_ms']:.0f}ms</div>
                <div class="vital-status">{vitals_status('inp_ms', vitals['inp_ms']).replace('_', ' ').title()}</div>
            </div>
            <div class="vital-card {vitals_status('ttfb_ms', vitals['ttfb_ms'])}">
                <div class="vital-name">TTFB</div>
                <div class="vital-value">{vitals['ttfb_ms']:.0f}ms</div>
                <div class="vital-status">{vitals_status('ttfb_ms', vitals['ttfb_ms']).replace('_', ' ').title()}</div>
            </div>
        </div>

        <h2>📈 Image Summary</h2>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value">{total_images}</div>
                <div class="stat-label">Total Images</div>
            </div>
            <div class="stat-box" style="background: #9b59b6;">
                <div class="stat-value">{total_bytes / 1024 / 1024:.2f} MB</div>
                <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-box" style="background: #e74c3c;">
                <div class="stat-value">{total_waste / 1024:.0f} KB</div>
                <div class="stat-label">Est. Waste</div>
            </div>
            <div class="stat-box" style="background: #27ae60;">
                <div class="stat-value">{avg_score:.0f}</div>
                <div class="stat-label">Avg Score</div>
            </div>
        </div>

        {f'''<div class="issues">
            <h3>⚠️ Top Issues</h3>
            <ul>
                {"".join(f"<li>{escape(issue)}</li>" for issue in summary['top_issues'])}
            </ul>
        </div>''' if summary['top_issues'] else ''}

        <h2>🖼️ Image Details</h2>
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
"""

    for img in images:
        score_class = "high" if img["score"] >= 75 else "medium" if img["score"] >= 50 else "low"
        src_display = img["src"][-50:] if len(img["src"]) > 50 else img["src"]

        displayed = f"{img.get('displayed_width', 'N/A')}×{img.get('displayed_height', 'N/A')}"
        natural = f"{img.get('natural_width', 'N/A')}×{img.get('natural_height', 'N/A')}"
        dimensions = f"{displayed}<br><small style='color:#888;'>({natural})</small>"

        lcp_badge = '<span class="lcp-badge">LCP</span> ' if img.get("is_lcp_candidate") else ""

        html += f"""                <tr>
                    <td class="bytes" title="{escape(img['src'])}">{lcp_badge}{escape(src_display)}</td>
                    <td><span class="role {escape(img['role'])}">{escape(img['role'].replace('_', ' '))}</span></td>
                    <td><span class="score {score_class}">{img['score']}</span></td>
                    <td class="bytes">{img['bytes'] / 1024:.1f} KB</td>
                    <td>{dimensions}</td>
                    <td class="bytes">{img.get('waste_bytes_est', 0) / 1024:.1f} KB</td>
                    <td class="recommendation">{escape(img.get('recommendation', '—'))}</td>
                </tr>
"""

    html += """            </tbody>
        </table>

        <h2>📋 Role Distribution</h2>
        <ul>
"""

    for role, count in sorted(role_counts.items()):
        role_escaped = escape(role)
        role_display = escape(role.replace("_", " "))
        html += f'            <li><span class="role {role_escaped}">{role_display}</span>: {count} image{"s" if count != 1 else ""}</li>\n'

    html += f"""        </ul>

        <footer>
            <p>Generated by shopify-image-audit v0.1</p>
            <p>Report generated from: {Path(audit_result.get('_source_file', 'audit_result.json')).name}</p>
        </footer>
    </div>
</body>
</html>
"""

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
    with open(audit_result_path, "r", encoding="utf-8") as f:
        audit_result = json.load(f)

    # Store source file for footer reference
    audit_result["_source_file"] = str(audit_result_path)

    html_content = generate_html_report(audit_result)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

