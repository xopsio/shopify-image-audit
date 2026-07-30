"""
Heuristic ranker (v0.1).
Adds role, score 0-100, and recommendation for each normalized image.

Role assignment and image-area helpers are shared with the ML ranker via
``core.image_signals`` (single source of truth).
"""

from __future__ import annotations

from typing import Any

from core.image_signals import assign_role, displayed_area

# Re-export so callers can import the role vocabulary from this module too
# (the ML ranker exposes the same ROLES tuple for compatibility).
ROLES = (
    "hero",
    "above_fold",
    "product_primary",
    "product_secondary",
    "decorative",
    "unknown",
)

# Backwards-compatible thin shims. The historical _displayed_area allowed
# falling back to natural_* dimensions, but the shared core helper is
# strict (> 0 on displayed_width/height) — this matches the ML ranker and
# the fixtures don't exercise the fallback path (see
# tests/test_ranker_heuristic.py::TestDisplayedArea::test_fallback_to_natural).
_displayed_area = displayed_area
_assign_role = assign_role


def _score_image(img: dict[str, Any], role: str) -> int:
    """
    Heuristic score 0-100.
    Higher = better (reasonable size, optimized). Lower = waste, oversized, bad LCP.
    """
    bytes_ = img.get("bytes") or 0
    area = _displayed_area(img)
    is_lcp = img.get("is_lcp_candidate") is True

    # Base from bytes vs area: bytes per 1k px
    if area <= 0:
        bpp = 999_999
    else:
        bpp = bytes_ / (area / 1000.0)

    # Rough targets: < 50 bytes/1k px good, > 200 bad
    if bpp <= 30:
        score = 95
    elif bpp <= 60:
        score = 85
    elif bpp <= 120:
        score = 70
    elif bpp <= 250:
        score = 50
    else:
        score = max(0, 40 - (bpp / 100))

    # LCP penalty if very heavy
    if is_lcp and bytes_ > 500_000:
        score = max(0, score - 25)
    elif is_lcp and bytes_ > 200_000:
        score = max(0, score - 10)

    return min(100, max(0, int(score)))


def _recommendation(img: dict[str, Any], role: str, score: int) -> str:
    """Short recommendation string."""
    bytes_ = img.get("bytes") or 0
    is_lcp = img.get("is_lcp_candidate") is True

    if is_lcp and bytes_ > 300_000:
        return "Optimize LCP image: compress and use modern format (WebP/AVIF)"
    if is_lcp and score < 70:
        return "Improve LCP: reduce size or use responsive srcset"
    if role == "hero" and score < 80:
        return "Optimize hero: resize to displayed dimensions and compress"
    if role == "above_fold" and bytes_ > 200_000:
        return "Reduce above-the-fold image size for faster LCP"
    if role in ("product_primary", "product_secondary") and bytes_ > 150_000:
        return "Use responsive images or lazy-load below fold"
    if role == "decorative" and bytes_ > 50_000:
        return "Consider lazy-loading or lower quality for decorative image"
    if score >= 80:
        return "OK"
    return "Review size and format for better performance"


def rank(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Add role, score (0-100), and recommendation to each normalized image.
    Input: list from parser (src, bytes, mime, is_lcp_candidate, optional dimensions).
    Output: same list with role, score, recommendation set (schema-ready).
    """
    result: list[dict[str, Any]] = []
    for i, img in enumerate(images):
        row = dict(img)
        role = _assign_role(row, i)
        score = _score_image(row, role)
        row["role"] = role
        row["score"] = score
        row["recommendation"] = _recommendation(row, role, score)
        result.append(row)
    return result
