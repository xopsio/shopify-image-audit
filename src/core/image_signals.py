"""
Shared image signals used by both rankers.

This module is the single source of truth for image-level features that are
common to both the heuristic ranker (``audit.ranker_heuristic.rank``) and
the ML-style ranker (``audit.ranker_ml.rank``):

- ``displayed_area(img)``: displayed pixel area, with strict > 0 contract
- ``assign_role(img, index)``: heuristic role assignment, byte-identical
  between both rankers (kept shared so role-vocabulary drift is impossible)

Score formulas remain ranker-specific (intentionally — that's the point of
having two rankers) and live in their own modules.

Why a separate module: extracted from ranker_heuristic.py and ranker_ml.py
to remove duplication and provide a stable contract for any future ranker.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Role vocabulary. Kept in sync with audit.models.ImageRole and the ROLES
# tuple in each ranker module.
ROLE_HERO = "hero"
ROLE_ABOVE_FOLD = "above_fold"
ROLE_PRODUCT_PRIMARY = "product_primary"
ROLE_PRODUCT_SECONDARY = "product_secondary"
ROLE_DECORATIVE = "decorative"
ROLE_UNKNOWN = "unknown"


class ImageDict(TypedDict, total=False):
    """Normalized image dict — the shared contract between parser,
    extractor, rankers, orchestrator and report renderer.

    Field names mirror ``audit_result.schema.json``'s image object.
    ``total=False`` because the fields are added progressively along the
    pipeline (extractor → ranker → orchestrator) before final validation
    into ``audit.models.ImageItem``.
    """

    src: str
    bytes: int
    mime: str
    displayed_width: int | None
    displayed_height: int | None
    natural_width: int | None
    natural_height: int | None
    is_lcp_candidate: bool
    role: str
    score: int
    waste_bytes_est: int
    recommendation: str | None


def _safe_int(value: Any) -> int:
    """Coerce ``value`` to int, returning 0 on failure or None.

    Used by both rankers to defend against malformed fixtures. ``None`` and
    non-numeric values become 0.
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def displayed_area(img: ImageDict) -> int:
    """Displayed pixel area, or 0 when dimensions are missing/invalid.

    Both width and height must be positive ints (> 0) for the area to be
    non-zero. Missing dimensions, zeros, or non-numeric values all yield 0.
    """
    w = _safe_int(img.get("displayed_width"))
    h = _safe_int(img.get("displayed_height"))
    return w * h if w > 0 and h > 0 else 0


def assign_role(img: ImageDict, index: int) -> str:
    """Assign a role to ``img`` based on its props and its position in the list.

    Uses the same vocabulary and thresholds as the original heuristic
    ranker (and the ML ranker that uses the same heuristic by design).
    Returns one of the ROLES constants.
    """
    is_lcp = bool(img.get("is_lcp_candidate"))
    area = displayed_area(img)
    bytes_ = _safe_int(img.get("bytes"))

    if is_lcp and area >= 200_000:
        return ROLE_HERO
    if is_lcp:
        return ROLE_ABOVE_FOLD
    if index == 0 and area >= 150_000:
        return ROLE_ABOVE_FOLD
    if area >= 100_000 and bytes_ > 50_000:
        return ROLE_PRODUCT_PRIMARY if index < 3 else ROLE_PRODUCT_SECONDARY
    if area < 30_000 or bytes_ < 5_000:
        return ROLE_DECORATIVE
    return ROLE_UNKNOWN
