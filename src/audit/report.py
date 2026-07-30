"""HTML report generation for audit results.

The report is assembled by focused, single-purpose render functions
(``_render_*``). ``generate_html_report`` is the public entry point and keeps
its original signature/contract so callers (CLI, tests) are unaffected.

A ``_render_comparison_section`` hook is reserved for before/after reporting
(Sprint 2, issue #20 / depends on #18). It currently renders nothing; its shape
will be finalised once the comparison data contract from #18 is ready.
"""

from __future__ import annotations

import base64
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
# Brand customisation (Sprint 4, TD-2)
# ---------------------------------------------------------------------------

#: Maximum logo file size for base64-embedded data URIs. Beyond this, we
#: warn and skip the logo to avoid bloating the report.
_BRAND_LOGO_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

#: Map of file extension to MIME type for supported logo formats.
#: SVGs are filtered for `<script>` tags at load time to avoid an injection
#: vector for embedded JavaScript in a self-contained data-URI report.
_BRAND_LOGO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _parse_brand_color(hex_str: str | None) -> str | None:
    """Validate and normalise a hex colour string.

    Accepts ``#RGB`` or ``#RRGGBB`` (case-insensitive). Returns the
    normalised ``#RRGGBB`` form, or ``None`` if the input is empty /
    invalid. Validation only — the caller is expected to log a warning
    on ``None`` and fall back to the default.
    """
    if not hex_str:
        return None
    s = hex_str.strip()
    if not s.startswith("#"):
        return None
    body = s[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    if len(body) != 6 or any(c not in "0123456789abcdefABCDEF" for c in body):
        return None
    return f"#{body.lower()}"


def _read_brand_logo(path: str | Path) -> tuple[str, str] | None:
    """Read a brand logo from disk for inline embedding in the HTML report.

    Returns ``(mime_type, base64_data)`` for use in a ``data:`` URI, or
    ``None`` if the file is missing, too large, has an unsupported
    extension, or is an SVG that contains ``<script>`` (a basic injection
    guard — not a full sanitiser).

    The caller is expected to log a warning on ``None`` and fall back to
    the default (no logo).
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        size = p.stat().st_size
    except OSError:
        return None
    if size > _BRAND_LOGO_MAX_BYTES:
        return None
    ext = p.suffix.lower()
    mime = _BRAND_LOGO_MIME.get(ext)
    if mime is None:
        return None
    try:
        data = p.read_bytes()
    except OSError:
        return None
    # Basic injection guard for SVGs: refuse any file containing a
    # <script> tag. This is NOT a complete sanitiser — it's a cheap
    # tripwire that catches the common "external SVG with embedded JS" case.
    if mime == "image/svg+xml" and b"<script" in data.lower():
        return None
    return mime, base64.b64encode(data).decode("ascii")


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
        .brand-logo {
            display: block;
            max-height: 80px;
            max-width: 240px;
            margin-bottom: 20px;
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
            border-bottom: 2px solid var(--brand-color, #3498db);
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
            background: var(--brand-color, #3498db);
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
        /* Before/after comparison section (#18/#20). */
        .comparison {
            margin: 20px 0;
        }
        .delta {
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.9em;
        }
        .delta.improved { background: #d4edda; color: #155724; }
        .delta.regressed { background: #f8d7da; color: #721c24; }
        .delta.unchanged { background: #e2e3e5; color: #383d41; }
        .status-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            color: white;
            font-size: 0.8em;
            font-weight: 500;
            text-transform: lowercase;
        }
        .roi-box {
            background: #e8f4fd;
            border-left: 4px solid var(--brand-color, #3498db);
            padding: 15px;
            margin: 15px 0;
        }"""


def _render_head(
    brand_logo: tuple[str, str] | None = None,
    brand_color: str | None = None,
) -> str:
    """Render the HTML document head, body open, and report title.

    Optional brand customisation:
    - ``brand_logo``: ``(mime_type, base64_data)`` from ``_read_brand_logo``.
      Rendered as an ``<img>`` above the title via a data URI, so the
      report is self-contained (no external file dependency).
    - ``brand_color``: validated hex colour, applied as a CSS variable
      so all brand-tinted elements pick it up automatically.
    """
    extra_css = ""
    if brand_color:
        extra_css = f"        :root {{ --brand-color: {brand_color}; }}\n"

    if brand_logo is not None:
        logo_mime, logo_b64 = brand_logo
        logo_tag = (
            f'    <img class="brand-logo" alt="Brand logo" '
            f'src="data:{logo_mime};base64,{logo_b64}">\n'
        )
    else:
        logo_tag = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shopify Image Audit Report</title>
    <style>
{extra_css}{_CSS}
    </style>
</head>
<body>
    <div class="container">
{logo_tag}        <h1>🖼️ Shopify Image Audit Report</h1>

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


def _render_comparison_delta_row(label: str, before: float, after: float, delta: float,
                                 delta_pct, fmt: str) -> str:
    """Render one before/after metric row in the comparison table."""
    if delta_pct is not None:
        pct_str = f" ({delta_pct:+.0f}%)"
    else:
        pct_str = ""

    # lower is better for every metric we compare
    if abs(delta) <= 1e-6:
        status = "unchanged"
    elif delta < 0:
        status = "improved"
    else:
        status = "regressed"

    sign = "+" if delta > 0 else ""
    delta_display = fmt.format(abs(delta)) if status == "improved" else fmt.format(delta)
    return f"""                <tr>
                    <td>{escape(label)}</td>
                    <td class="bytes">{fmt.format(before)}</td>
                    <td class="bytes">{fmt.format(after)}</td>
                    <td><span class="delta {status}">{sign}{delta_display}{pct_str}</span></td>
                </tr>
"""


def _render_comparison_section(comparison) -> str:
    """Render the before/after comparison section.

    Returns an empty string when ``comparison`` is None (the default, so
    existing single-audit reports are unaffected). Accepts a
    ``ComparisonResult`` model or its dict form.
    """
    if comparison is None:
        return ""
    # Normalise to a plain dict so this works with a model or a dict.
    if hasattr(comparison, "model_dump"):
        comparison = comparison.model_dump()

    before_url = escape(str(comparison.get("before", {}).get("url", "")))
    after_url = escape(str(comparison.get("after", {}).get("url", "")))
    vitals = comparison["vitals"]
    img_stats = comparison["images"]
    summary = comparison.get("summary", {})
    per_image = comparison.get("per_image", [])

    # Vital metric rows: (label, vital_key, format)
    rows = ""
    for label, key, fmt in (
        ("LCP", "lcp", "{:.0f}ms"),
        ("CLS", "cls", "{:.3f}"),
        ("INP", "inp", "{:.0f}ms"),
        ("TTFB", "ttfb", "{:.0f}ms"),
    ):
        d = vitals[key]
        rows += _render_comparison_delta_row(label, d["before"], d["after"], d["delta"], d.get("delta_pct"), fmt)

    # Image-level aggregate rows
    img_rows = ""
    img_rows += _render_comparison_delta_row(
        "Total image bytes", img_stats["before_total_bytes"], img_stats["after_total_bytes"],
        img_stats["total_bytes_delta"], None, "{:.0f}"
    )
    img_rows += _render_comparison_delta_row(
        "Estimated waste", img_stats["before_total_waste"], img_stats["after_total_waste"],
        img_stats["total_waste_delta"], None, "{:.0f}"
    )
    img_rows += _render_comparison_delta_row(
        "Avg image score", img_stats["before_avg_score"], img_stats["after_avg_score"],
        img_stats["avg_score_delta"], None, "{:.1f}"
    )

    improvements = summary.get("top_improvements", [])
    regressions = summary.get("top_regressions", [])
    roi = summary.get("roi_estimate", "")

    # Per-image delta table (rendered only if the comparison has per-image data)
    per_image_html = _render_per_image_deltas(per_image)

    improvement_items = "".join(f"<li>{escape(i)}</li>" for i in improvements)
    regression_items = "".join(f"<li>{escape(i)}</li>" for i in regressions)
    regressions_block = (
        f'<h3 style="color:#c0392b;">⚠️ Regressions</h3><ul>{regression_items}</ul>'
        if regressions else ""
    )

    return f"""        <div class="comparison">
            <h2>🔄 Before / After Comparison</h2>
            <p><strong>Before:</strong> {before_url} &nbsp; → &nbsp; <strong>After:</strong> {after_url}</p>
            <h3>Core Web Vitals</h3>
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Before</th>
                        <th>After</th>
                        <th>Change</th>
                    </tr>
                </thead>
                <tbody>
{rows}                </tbody>
            </table>
            <h3>Image Optimisation</h3>
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Before</th>
                        <th>After</th>
                        <th>Change</th>
                    </tr>
                </thead>
                <tbody>
{img_rows}                </tbody>
            </table>
{per_image_html}            <h3 style="color:#27ae60;">✅ Improvements</h3>
            <ul>{improvement_items}</ul>
            {regressions_block}
            <div class="roi-box">
                <strong>ROI estimate:</strong> {escape(roi)}
            </div>
        </div>

"""


def _render_per_image_deltas(per_image: list[dict[str, Any]]) -> str:
    """Render a per-image before/after delta table for the comparison section.

    Each row shows one image: src (truncated), role change, bytes delta,
    score delta, and a coloured status badge. Added/removed/re-encoded
    images are visually distinguished. Returns an empty string when
    ``per_image`` is empty so a single-audit report is unaffected.
    """
    if not per_image:
        return ""

    status_colours = {
        "improved": "#27ae60",   # green
        "regressed": "#c0392b",   # red
        "unchanged": "#7f8c8d",   # grey
        "added": "#2980b9",      # blue
        "removed": "#95a5a6",    # light grey
    }

    rows = []
    for d in per_image:
        status = d.get("status", "unchanged")
        colour = status_colours.get(status, "#7f8c8d")

        # Cell formatters — handle None for added/removed cases.
        def fmt_bytes(b: int | None) -> str:
            if b is None:
                return "—"
            sign = "+" if b > 0 else ""
            return f"{sign}{b / 1024:.1f} KB"

        def fmt_score(s: int | None) -> str:
            if s is None:
                return "—"
            sign = "+" if s > 0 else ""
            return f"{sign}{s}"

        def fmt_role(rb: str | None, ra: str | None) -> str:
            if rb == ra:
                return escape(rb or "—")
            return f"{escape(rb or '—')} → {escape(ra or '—')}"

        src = escape(str(d.get("src") or "—")[-50:])
        bytes_delta = fmt_bytes(d.get("bytes_delta"))
        score_delta = fmt_score(d.get("score_delta"))
        role = fmt_role(d.get("role_before"), d.get("role_after"))
        rec = escape(str(d.get("recommendation") or ""))

        rows.append(f"""                <tr>
                    <td>{src}</td>
                    <td>{role}</td>
                    <td>{bytes_delta}</td>
                    <td>{score_delta}</td>
                    <td><span class="status-badge" style="background:{colour};">{status}</span></td>
                    <td class="recommendation">{rec}</td>
                </tr>""")

    return f"""            <h3>📸 Per-Image Changes</h3>
            <table>
                <thead>
                    <tr>
                        <th>Source</th>
                        <th>Role</th>
                        <th>Bytes</th>
                        <th>Score</th>
                        <th>Status</th>
                        <th>Recommendation</th>
                    </tr>
                </thead>
                <tbody>
{chr(10).join(rows)}                </tbody>
            </table>
"""


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

def generate_html_report(
    audit_result: dict[str, Any],
    comparison=None,
    *,
    brand_logo: tuple[str, str] | None = None,
    brand_color: str | None = None,
) -> str:
    """
    Generate an HTML report from an audit result dictionary.

    Args:
        audit_result: Validated audit result dictionary matching the schema
        comparison: Optional before/after comparison. A ``ComparisonResult``
            model or its dict form. When provided, a "Before / After Comparison"
            section is rendered after the top-issues block. Defaults to None
            (no comparison section — original behaviour).
        brand_logo: Optional ``(mime_type, base64_data)`` tuple from
            ``_read_brand_logo``. Rendered as a data-URI image at the top
            of the report.
        brand_color: Optional validated hex colour (e.g. ``"#ff6b35"``).
            Applied as a CSS variable so all brand-tinted elements pick it
            up. Invalid values are ignored — call sites are expected to
            validate before calling.

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

    html = _render_head(brand_logo=brand_logo, brand_color=brand_color)
    html += _render_meta(meta)
    html += _render_vitals(vitals)
    html += _render_stats(stats)
    html += _render_issues(summary)
    html += _render_comparison_section(comparison)
    html += _render_image_table(images)
    html += _render_role_distribution(stats["role_counts"])
    html += _render_footer(audit_result)

    return html


def _create_pdf_url_fetcher() -> Any:
    """Create a PDF resource fetcher that only permits embedded data URLs.

    Policy violations are fatal so rendering never silently ignores an
    attempted external fetch.
    """
    from weasyprint.urls import URLFetcher

    return URLFetcher(allowed_protocols=("data",), fail_on_errors=True)


def render_pdf_report(html_content: str, output_path: Path | str) -> Path:
    """
    Render an HTML report string to a PDF file using WeasyPrint.

    The HTML must already be fully assembled (use ``generate_html_report`` or
    its callers). The output file is created or overwritten. Parent dirs
    are created as needed.
    Resource references are restricted to embedded ``data:`` URLs; all other
    protocols are rejected before I/O.

    Returns the resolved output path.

    Raises:
        ImportError: if WeasyPrint is not installed (the runtime dependency
            ``weasyprint>=69.0,<70`` should make this impossible in practice;
            it surfaces here only if the install is broken).
        weasyprint.urls.FatalURLFetchingError: if the HTML references a
            resource outside the allowed ``data:`` protocol.
        OSError: if WeasyPrint cannot write the PDF (e.g. fontconfig or
            pango missing on the host).
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Lazy import so CLI commands that never produce a PDF don't pay the
    # ~200 ms WeasyPrint import cost.
    import weasyprint

    url_fetcher = _create_pdf_url_fetcher()
    weasyprint.HTML(string=html_content, url_fetcher=url_fetcher).write_pdf(target=str(output))
    return output


def write_html_report(
    audit_result_path: Path,
    output_path: Path,
    *,
    brand_logo: str | Path | None = None,
    brand_color: str | None = None,
) -> None:
    """
    Read an audit result JSON file and write an HTML report.

    Args:
        audit_result_path: Path to the audit_result.json file
        output_path: Path where the HTML report should be written
        brand_logo: Optional path to a brand logo file (PNG, JPG, GIF, WebP, SVG).
            Embedded as a data URI in the report header. Invalid/missing
            files are ignored (the report renders without a logo).
        brand_color: Optional hex colour string (e.g. ``"#ff6b35"``).
            Invalid values are ignored (default palette is used).

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

    html_content = generate_html_report(
        audit_result,
        brand_logo=_read_brand_logo(brand_logo) if brand_logo else None,
        brand_color=_parse_brand_color(brand_color),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
