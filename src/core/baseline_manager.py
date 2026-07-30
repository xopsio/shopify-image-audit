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

import hashlib
import json
from pathlib import Path
from typing import Any

from audit.models import (
    AuditResult,
    ComparisonResult,
    ComparisonSummary,
    ImageDelta,
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
# Per-image matching and delta computation
# ---------------------------------------------------------------------------

def _strip_query_params(src: str) -> str:
    """Remove ``?key=value`` query params from a URL/path.

    Used to normalise URLs before hashing so that CDN cache-busting
    suffixes (e.g. ``?v=2``) don't break per-image matching.
    """
    return src.split("?", 1)[0]


def _image_key(img: dict[str, Any]) -> str:
    """Stable identifier for matching an image across two AuditResults.

    Hash over (normalised src, bytes, mime). This tolerates CDN
    cache-busting query params (which are stripped before hashing) but
    treats genuine data changes — format conversion (JPEG → WebP) or
    re-encoded content — as different images.

    The key is short (8 hex chars) and stable; collisions in 2^32 are
    astronomically unlikely across realistic audit pairs.
    """
    src = _strip_query_params(str(img.get("src", "")))
    bytes_ = int(img.get("bytes") or 0)
    mime = str(img.get("mime") or "")
    payload = f"{src}|{bytes_}|{mime}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _per_image_status(before_bytes: int, after_bytes: int) -> str:
    """Derive a per-image status from byte delta.

    Heuristic: a byte reduction of >=10% is "improved", increase of >=10%
    is "regressed", otherwise "unchanged". Mime changes are not part of
    the status — those show up in the recommendation string.
    """
    if before_bytes <= 0:
        return "unchanged"
    pct = (after_bytes - before_bytes) / before_bytes
    if pct <= -0.10:
        return "improved"
    if pct >= 0.10:
        return "regressed"
    return "unchanged"


def _per_image_recommendation(status: str, mime_before: str | None,
                              mime_after: str | None, score_delta: int) -> str:
    """A short per-image recommendation string for the report table."""
    if status == "added":
        if mime_after and mime_after not in ("image/webp", "image/avif", "image/jxl"):
            return "New image; consider WebP/AVIF."
        return "New image."
    if status == "removed":
        return "Image removed."
    if status == "regressed":
        return "Image grew; review."
    if status == "improved" and mime_before and mime_after and mime_before != mime_after:
        return f"Format converted: {mime_before.split('/')[-1]} → {mime_after.split('/')[-1]}."
    if status == "improved" and score_delta > 0:
        return f"Score improved by {score_delta} points."
    return ""


def _match_images(
    before_imgs: list[dict[str, Any]],
    after_imgs: list[dict[str, Any]],
) -> list[ImageDelta]:
    """Pair images between before/after and produce per-image deltas.

    Two-phase matching:
    1. **Primary: hash match.** Pair by ``_image_key(img)`` (normalised src
       + bytes + mime). Two images with the same data hash are the same
       image even if the CDN appended cache-busting query params.
    2. **Fallback: src match.** If hash doesn't match but the normalised
       src matches exactly, pair them. This catches "same URL, slightly
       different bytes" (e.g. a re-encoding that only changes a few bytes
       due to compression nondeterminism).

    Unmatched before-images are "removed"; unmatched after-images are
    "added". Matched pairs get bytes/score deltas.
    """
    # Index after-images by key for fast lookup (primary match).
    after_by_key: dict[str, dict[str, Any]] = {}
    for img in after_imgs:
        key = _image_key(img)
        if key not in after_by_key:
            after_by_key[key] = img

    # Secondary index: normalised src -> image (for fallback match).
    after_by_src: dict[str, dict[str, Any]] = {}
    for img in after_imgs:
        src = _strip_query_params(str(img.get("src", "")))
        if src and src not in after_by_src:
            after_by_src[src] = img

    consumed: set[int] = set()
    deltas: list[ImageDelta] = []

    for b_img in before_imgs:
        b_key = _image_key(b_img)
        b_src_norm = _strip_query_params(str(b_img.get("src", "")))

        # Primary: hash match.
        a_img = after_by_key.get(b_key)
        match_kind: str | None = "hash" if a_img is not None else None

        # Fallback: src match (only if hash didn't match).
        if a_img is None and b_src_norm:
            a_img = after_by_src.get(b_src_norm)
            if a_img is not None:
                match_kind = "src"

        if a_img is None:
            # No match — image removed.
            deltas.append(ImageDelta(
                match_key=b_key,
                src=str(b_img.get("src", "")),
                role_before=b_img.get("role"),
                before=b_img,
                status="removed",
                mime_before=b_img.get("mime"),
                recommendation=_per_image_recommendation(
                    "removed", b_img.get("mime"), None, 0,
                ),
            ))
            continue

        # Mark the matched after-image as consumed.
        consumed.add(id(a_img))

        b_bytes = int(b_img.get("bytes") or 0)
        a_bytes = int(a_img.get("bytes") or 0)
        b_score = int(b_img.get("score") or 0)
        a_score = int(a_img.get("score") or 0)
        status = _per_image_status(b_bytes, a_bytes)
        # When matched via src (not hash), there's a genuine data change —
        # the recommendation should reflect that this is a "same URL,
        # different bytes" case.
        rec = _per_image_recommendation(
            status, b_img.get("mime"), a_img.get("mime"), a_score - b_score,
        )
        if match_kind == "src" and status == "unchanged" and not rec:
            rec = "Image re-encoded (same URL, bytes changed)."

        deltas.append(ImageDelta(
            match_key=b_key,
            src=str(a_img.get("src") or b_img.get("src", "")),
            role_before=b_img.get("role"),
            role_after=a_img.get("role"),
            before=b_img,
            after=a_img,
            bytes_delta=a_bytes - b_bytes,
            score_delta=a_score - b_score,
            mime_before=b_img.get("mime"),
            mime_after=a_img.get("mime"),
            status=status,
            recommendation=rec,
        ))

    # Any after-image not consumed is "added".
    for a_img in after_imgs:
        if id(a_img) in consumed:
            continue
        a_key = _image_key(a_img)
        a_bytes = int(a_img.get("bytes") or 0)
        deltas.append(ImageDelta(
            match_key=a_key,
            src=str(a_img.get("src", "")),
            role_after=a_img.get("role"),
            after=a_img,
            bytes_delta=a_bytes,
            mime_after=a_img.get("mime"),
            status="added",
            recommendation=_per_image_recommendation(
                "added", None, a_img.get("mime"), 0,
            ),
        ))

    return deltas


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
    per_image = _match_images(b_imgs, a_imgs)
    return ComparisonResult(
        before={"url": b["meta"]["url"], "timestamp_utc": b["meta"]["timestamp_utc"]},
        after={"url": a["meta"]["url"], "timestamp_utc": a["meta"]["timestamp_utc"]},
        vitals=vitals,
        images=images,
        summary=summary,
        per_image=per_image,
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
