"""
Before/after measurement engine (Sprint 2, #18).

Provides baseline persistence and comparison between two ``AuditResult``
measurements. The comparison computes Core Web Vitals deltas plus aggregate
image-level changes and a simple ROI estimate.

Design notes
------------
- Units mirror the ``Vitals`` model: ms for LCP/INP/TTFB, unitless for CLS.
- "lower is better" for every metric we compare, so a negative delta is an
  *improvement*.
- This module knows nothing about the CLI or HTML; it produces a
  ``ComparisonResult`` that those layers consume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audit.models import (
    AuditResult,
    ComparisonResult,
    ComparisonSummary,
    ImageStatsDelta,
    MetricDelta,
    VitalsDelta,
)

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_baseline(audit_result: AuditResult, path: str | Path) -> Path:
    """Write an ``AuditResult`` to ``path`` as schema-compliant JSON.

    Returns the resolved path. Parent directories are created as needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(audit_result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_baseline(path: str | Path) -> AuditResult:
    """Load and validate a saved baseline from ``path``.

    Raises ``FileNotFoundError`` if missing, ``json.JSONDecodeError`` on bad
    JSON, and ``pydantic.ValidationError`` if the payload is not a valid
    ``AuditResult``.
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return AuditResult.model_validate(raw)


# ---------------------------------------------------------------------------
# Delta helpers
# ---------------------------------------------------------------------------

# Metrics where lower is better. Every metric we compare (LCP, CLS, INP, TTFB)
# qualifies, but keeping the set explicit documents the convention and leaves
# room for higher-is-better metrics later (e.g. performance_score).
_LOWER_IS_BETTER = {"lcp", "cls", "inp", "ttfb"}

# Absolute tolerance: deltas within this band are "unchanged". Tuned to avoid
# float noise flipping a status for tiny real-world changes.
_UNCHANGED_TOLERANCE = 1e-6


def _delta(before: float, after: float, *, lower_is_better: bool) -> MetricDelta:
    """Compute a MetricDelta (after - before) and derive its status."""
    delta = after - before
    delta_pct: float | None = None
    if abs(before) > _UNCHANGED_TOLERANCE:
        delta_pct = (delta / before) * 100.0

    if abs(delta) <= _UNCHANGED_TOLERANCE:
        status = "unchanged"
    elif lower_is_better:
        status = "improved" if delta < 0 else "regressed"
    else:
        status = "improved" if delta > 0 else "regressed"

    return MetricDelta(
        before=before,
        after=after,
        delta=delta,
        delta_pct=delta_pct,
        status=status,
    )


def _avg_score(images: list[dict[str, Any]]) -> float:
    if not images:
        return 0.0
    return sum(img.get("score", 0) for img in images) / len(images)


def _total_bytes(images: list[dict[str, Any]]) -> int:
    return sum(img.get("bytes", 0) for img in images)


def _total_waste(images: list[dict[str, Any]]) -> int:
    return sum(img.get("waste_bytes_est", 0) or 0 for img in images)


# ---------------------------------------------------------------------------
# ROI heuristic
# ---------------------------------------------------------------------------

def _roi_estimate(vitals: VitalsDelta, images: ImageStatsDelta) -> str:
    """Simple, clearly-labelled ROI heuristic.

    Based on the widely-cited rule of thumb that each 100ms of LCP improvement
    correlates with ~1% conversion uplift (Google/SOASTA research). This is an
    *estimate*, not a measurement — the string is written so a customer report
    can present it as an approximation.
    """
    lcp_ms_improved = max(0.0, -vitals.lcp.delta)
    if lcp_ms_improved < 50:
        if images.total_waste_delta < 0:
            return "Image payload reduced; expect modest performance gain."
        return "No significant LCP change detected."

    pct = lcp_ms_improved / 100.0
    return (
        f"Estimated ~{pct:.0f}% conversion uplift from a "
        f"{lcp_ms_improved:.0f}ms LCP improvement "
        f"(heuristic: ~1% per 100ms LCP)."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare(before: AuditResult, after: AuditResult) -> ComparisonResult:
    """Compare two ``AuditResult`` measurements and return a ``ComparisonResult``.

    Both inputs are normalised to plain dicts for arithmetic so this works with
    full ``AuditResult`` models or their ``model_dump()`` output.
    """
    b = before.model_dump() if isinstance(before, AuditResult) else dict(before)
    a = after.model_dump() if isinstance(after, AuditResult) else dict(after)

    bv, av = b["vitals"], a["vitals"]
    vitals = VitalsDelta(
        lcp=_delta(bv["lcp_ms"], av["lcp_ms"], lower_is_better=True),
        cls=_delta(bv["cls"], av["cls"], lower_is_better=True),
        inp=_delta(bv["inp_ms"], av["inp_ms"], lower_is_better=True),
        ttfb=_delta(bv["ttfb_ms"], av["ttfb_ms"], lower_is_better=True),
    )

    b_imgs, a_imgs = b.get("images", []), a.get("images", [])
    before_total_bytes = _total_bytes(b_imgs)
    after_total_bytes = _total_bytes(a_imgs)
    before_total_waste = _total_waste(b_imgs)
    after_total_waste = _total_waste(a_imgs)
    before_avg = _avg_score(b_imgs)
    after_avg = _avg_score(a_imgs)

    images = ImageStatsDelta(
        before_count=len(b_imgs),
        after_count=len(a_imgs),
        count_delta=len(a_imgs) - len(b_imgs),
        before_total_bytes=before_total_bytes,
        after_total_bytes=after_total_bytes,
        total_bytes_delta=after_total_bytes - before_total_bytes,
        before_total_waste=before_total_waste,
        after_total_waste=after_total_waste,
        total_waste_delta=after_total_waste - before_total_waste,
        before_avg_score=before_avg,
        after_avg_score=after_avg,
        avg_score_delta=after_avg - before_avg,
    )

    summary = _build_summary(vitals, images)
    return ComparisonResult(
        before={"url": b["meta"]["url"], "timestamp_utc": b["meta"]["timestamp_utc"]},
        after={"url": a["meta"]["url"], "timestamp_utc": a["meta"]["timestamp_utc"]},
        vitals=vitals,
        images=images,
        summary=summary,
    )


# Human-readable labels + formatters per vital, for summary building.
_VITAL_LABELS = (
    ("LCP", "lcp", "{:.0f}ms"),
    ("CLS", "cls", "{:.3f}"),
    ("INP", "inp", "{:.0f}ms"),
    ("TTFB", "ttfb", "{:.0f}ms"),
)


def _build_summary(vitals: VitalsDelta, images: ImageStatsDelta) -> ComparisonSummary:
    """Produce human-readable improvement/regression lines + ROI estimate."""
    improvements: list[str] = []
    regressions: list[str] = []

    for label, key, fmt in _VITAL_LABELS:
        delta_obj: MetricDelta = getattr(vitals, key)
        if delta_obj.status == "unchanged":
            continue
        pct = f" ({delta_obj.delta_pct:+.0f}%)" if delta_obj.delta_pct is not None else ""
        line = f"{label} {fmt.format(delta_obj.before)} → {fmt.format(delta_obj.after)}{pct}"
        (improvements if delta_obj.status == "improved" else regressions).append(line)

    # Image payload improvements (lower bytes/waste = better)
    if images.total_bytes_delta < 0:
        improvements.append(
            f"Image payload {images.before_total_bytes / 1024:.0f} KB → "
            f"{images.after_total_bytes / 1024:.0f} KB"
        )
    elif images.total_bytes_delta > 0:
        regressions.append(
            f"Image payload {images.before_total_bytes / 1024:.0f} KB → "
            f"{images.after_total_bytes / 1024:.0f} KB"
        )

    if images.total_waste_delta < 0:
        improvements.append(f"Estimated waste reduced by {abs(images.total_waste_delta) / 1024:.0f} KB")
    elif images.total_waste_delta > 0:
        regressions.append(f"Estimated waste increased by {images.total_waste_delta / 1024:.0f} KB")

    if images.avg_score_delta > 0:
        improvements.append(f"Average image score {images.before_avg_score:.0f} → {images.after_avg_score:.0f}")
    elif images.avg_score_delta < 0:
        regressions.append(f"Average image score {images.before_avg_score:.0f} → {images.after_avg_score:.0f}")

    if not improvements and not regressions:
        improvements.append("No measurable changes between the two audits.")

    return ComparisonSummary(
        top_improvements=improvements,
        top_regressions=regressions,
        roi_estimate=_roi_estimate(vitals, images),
    )
