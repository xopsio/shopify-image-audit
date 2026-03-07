"""
Heuristic ranker (v0.1).
Adds role, score 0-100, and recommendation for each normalized image.
"""

from __future__ import annotations

from typing import Any

ROLES = (
    "hero",
    "above_fold",
    "product_primary",
    "product_secondary",
    "decorative",
    "unknown",
)


def _displayed_area(img: dict[str, Any]) -> int:
    """Displayed pixel area; 0 if dimensions missing."""
    w = img.get("displayed_width") or img.get("natural_width") or 0
    h = img.get("displayed_height") or img.get("natural_height") or 0
    return w * h if w and h else 0


def _assign_role(img: dict[str, Any], index: int) -> str:
    """Heuristic role from image props and position."""
    is_lcp = img.get("is_lcp_candidate") is True
    area = _displayed_area(img)
    bytes_ = img.get("bytes") or 0

    if is_lcp and area >= 200_000:  # large LCP → hero
        return "hero"
    if is_lcp:
        return "above_fold"
    if index == 0 and area >= 150_000:
        return "above_fold"
    if area >= 100_000 and bytes_ > 50_000:
        return "product_primary" if index < 3 else "product_secondary"
    if area < 30_000 or bytes_ < 5_000:
        return "decorative"
    return "unknown"


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
