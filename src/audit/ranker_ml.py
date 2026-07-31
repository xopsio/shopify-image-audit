"""
ML-style image ranker — Sprint 3.

Drop-in replacement for ``audit.ranker_heuristic.rank``. Same input/output
contract: takes a list of normalized image dicts (output of ``audit.parser.parse``)
and returns a list of dicts that have ``role``, ``score`` and ``recommendation``
added, with all original fields preserved.

Design
------
This is a "weighted feature ensemble" — not a statistical model. Five normalised
features ([0, 1] each) are combined with fixed weights; LCP candidates are
scored more strictly. The output is deterministic, fully explainable
(``ml_features()`` exposes the per-image signal vector), and easily
replaceable with a true ML model later (same input/output shape).

Why not a real model: governance v1.3 calls for simple, testable, deterministic
solutions. A real ML model would add a runtime dependency, require training
data, and produce opaque decisions. The current ensemble gives 80% of the value
at 0% of the operational complexity.

Features (all in [0, 1]; higher = better):
    f_size       log-scaled bytes (50 KB -> 1.0, 2.5 MB -> 0.0)
    f_density    bytes per displayed 1k pixels (300 bpp -> 0.0)
    f_format     modern (WebP/AVIF/JXL/SVG) = 1.0, legacy = 0.0
    f_dim_match  natural vs displayed dimensions ratio (1.0 = perfect fit)

Combined score: 0.45*f_size + 0.30*f_density + 0.15*f_format + 0.10*f_dim_match,
scaled to 0-100. LCP candidates get a multiplicative 0.85 and an additional
penalty when bytes > 300_000.
"""

from __future__ import annotations

import math
from typing import cast

from core.image_signals import ImageDict, _safe_int, assign_role, displayed_area

# Same role vocabulary as ranker_heuristic (and the ImageRole enum).
ROLES = (
    "hero",
    "above_fold",
    "product_primary",
    "product_secondary",
    "decorative",
    "unknown",
)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

# Feature weights — combined into the base score before LCP adjustment.
_W_SIZE = 0.45
_W_DENSITY = 0.30
_W_FORMAT = 0.15
_W_DIM_MATCH = 0.10

# Modern image formats (matches the legacy ranker's intent + SVG).
_MODERN_MIME_HINTS = ("image/webp", "image/avif", "image/jxl", "image/svg+xml")

# Size scoring calibration: 50 KB -> 1.0, 2.5 MB -> 0.0 (log scale).
_SIZE_FLOOR = 50_000          # bytes at which f_size = 1.0
_SIZE_CEIL = 2_500_000        # bytes at which f_size = 0.0

# Density scoring calibration: bytes per 1k displayed pixels at which f_density = 0.
_DENSITY_CEIL = 300.0


# Backwards-compatible aliases for the public API. The shared helpers in
# ``core.image_signals`` are the single source of truth.
_displayed_area = displayed_area


def _f_size(bytes_: int) -> float:
    """Log-scaled byte score in [0, 1]."""
    if bytes_ <= _SIZE_FLOOR:
        return 1.0
    if bytes_ >= _SIZE_CEIL:
        return 0.0
    # Linear interpolation on log10 between floor (1.0) and ceil (0.0).
    log_floor = math.log10(_SIZE_FLOOR)
    log_ceil = math.log10(_SIZE_CEIL)
    log_val = math.log10(max(bytes_, 1))
    return max(0.0, 1.0 - (log_val - log_floor) / (log_ceil - log_floor))


def _f_density(bytes_: int, area: int) -> float:
    """Bytes per 1k displayed pixels, scaled to [0, 1]."""
    if area <= 0:
        # No displayed dimensions: cannot assess density.
        return 0.0
    bpp = bytes_ / (area / 1000.0)
    return max(0.0, 1.0 - bpp / _DENSITY_CEIL)


def _f_format(mime: str) -> float:
    """Modern format (WebP/AVIF/JXL/SVG) = 1.0, legacy = 0.0."""
    mime_lower = (mime or "").lower()
    if any(hint in mime_lower for hint in _MODERN_MIME_HINTS):
        return 1.0
    return 0.0


def _f_dim_match(img: ImageDict) -> float:
    """Match between natural and displayed dimensions.

    1.0 = perfect (within 1.5x); 0.0 = ratio >= 4 (image 4x or more oversized).
    Linear interpolation between. When natural dimensions are unknown, return
    1.0 (don't penalise for missing data — assume the developer is fine).
    """
    dw = _safe_int(img.get("displayed_width"))
    dh = _safe_int(img.get("displayed_height"))
    nw = _safe_int(img.get("natural_width"))
    nh = _safe_int(img.get("natural_height"))

    if dw <= 0 or dh <= 0 or nw <= 0 or nh <= 0:
        return 1.0  # no info, no penalty

    ratio_w = max(nw, dw) / min(nw, dw)
    ratio_h = max(nh, dh) / min(nh, dh)
    # Take the worse of the two axes.
    ratio = max(ratio_w, ratio_h)

    if ratio <= 1.5:
        return 1.0
    if ratio >= 4.0:
        return 0.0
    # Linear: 1.0 at ratio=1.5, 0.0 at ratio=4.0
    return 1.0 - (ratio - 1.5) / (4.0 - 1.5)


def _features(img: ImageDict) -> dict[str, float]:
    """Return the full normalised feature vector for an image.

    Exposed for explainability + tests.
    """
    bytes_ = _safe_int(img.get("bytes"))
    area = _displayed_area(img)
    mime = str(img.get("mime") or "")
    return {
        "f_size": _f_size(bytes_),
        "f_density": _f_density(bytes_, area),
        "f_format": _f_format(mime),
        "f_dim_match": _f_dim_match(img),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_from_features(f: dict[str, float], *, is_lcp: bool, bytes_: int) -> int:
    """Combine features into a 0-100 score."""
    base = (
        _W_SIZE * f["f_size"]
        + _W_DENSITY * f["f_density"]
        + _W_FORMAT * f["f_format"]
        + _W_DIM_MATCH * f["f_dim_match"]
    )
    if is_lcp:
        base *= 0.85
        # Extra penalty for very heavy LCP candidates (aligns with heuristic).
        if bytes_ > 300_000:
            base -= 0.10

    score = base * 100
    return max(0, min(100, int(score)))


# ---------------------------------------------------------------------------
# Role assignment (mirrors heuristic thresholds for cross-ranker consistency)
# ---------------------------------------------------------------------------

def _role_from_features(img: ImageDict, features: dict[str, float], index: int) -> str:
    """Assign a role using the shared heuristic from ``core.image_signals``.

    Kept as a thin shim with the original signature for backwards compat
    (tests import ``_role_from_features(img, feats, index)``; ``features``
    is unused but preserved).
    """
    return assign_role(img, index)


# ---------------------------------------------------------------------------
# Recommendation text
# ---------------------------------------------------------------------------

def _recommendation(score: int, is_lcp: bool, features: dict[str, float],
                    bytes_: int) -> str:
    """Human-readable recommendation string, tailored to the ML signals."""
    if score >= 85:
        return "OK"

    parts: list[str] = []

    if is_lcp and bytes_ > 300_000:
        parts.append("Optimize LCP image: compress and use modern format")
    elif is_lcp and score < 70:
        parts.append("Improve LCP: reduce size or use responsive srcset")

    # Modern-format nudge: only when the format signal shows it's legacy.
    if features["f_format"] == 0.0:
        parts.append("Convert to WebP/AVIF for ~30% size reduction")

    if features["f_dim_match"] < 0.5:
        parts.append("Resize to displayed dimensions to cut bytes")

    if features["f_density"] < 0.4:
        parts.append("Reduce image density (bytes per pixel)")

    if not parts:
        parts.append("Review size and format for better performance")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Public API (drop-in for audit.ranker_heuristic.rank)
# ---------------------------------------------------------------------------

def rank(images: list[ImageDict]) -> list[ImageDict]:
    """
    Add role, score, and recommendation to each image, preserving all input keys.

    Mirrors the contract of ``audit.ranker_heuristic.rank`` so it can be used as
    a drop-in replacement. See ``audit_orchestrator.run_audit(ranker='ml')``.
    """
    result: list[ImageDict] = []
    for i, img in enumerate(images):
        # Runtime copy: fixtures may carry extra keys beyond ImageDict; the
        # copy still satisfies the ImageDict contract.
        row = cast(ImageDict, dict(img))  # preserve all input keys
        feats = _features(img)
        bytes_ = _safe_int(img.get("bytes"))
        is_lcp = bool(img.get("is_lcp_candidate"))

        row["role"] = _role_from_features(img, feats, i)
        row["score"] = _score_from_features(feats, is_lcp=is_lcp, bytes_=bytes_)
        row["recommendation"] = _recommendation(row["score"], is_lcp, feats, bytes_)
        result.append(row)
    return result


def ml_features(img: ImageDict) -> dict[str, float]:
    """Public accessor for the per-image feature vector (explainability)."""
    return _features(img)
