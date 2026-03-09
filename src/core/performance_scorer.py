from __future__ import annotations

from typing import Any, Dict


MODERN_MIME_HINTS = ("image/webp", "image/avif", "image/jxl")


def _is_modern_format(mime: str) -> bool:
    """Return True if mime looks like a modern image format (WebP/AVIF/JXL)."""
    lower = mime.lower()
    return any(hint in lower for hint in MODERN_MIME_HINTS)


def calculate_score(image: Dict[str, Any]) -> int:
    """
    Heuristic performance score for a single image (0–100).

    v1 heuristic focuses on:
    - bytes (overall transfer size)
    - modern format (WebP/AVIF/JXL bonus)
    - LCP candidate penalty if heavy
    """
    if not isinstance(image, dict):
        return 0

    raw_bytes = image.get("bytes") or 0
    try:
        bytes_ = int(raw_bytes)
    except (TypeError, ValueError):
        bytes_ = 0

    mime = str(image.get("mime") or "")
    is_lcp = bool(image.get("is_lcp_candidate"))

    # Base score from absolute size.
    if bytes_ <= 50_000:
        score = 95
    elif bytes_ <= 150_000:
        score = 85
    elif bytes_ <= 300_000:
        score = 70
    elif bytes_ <= 600_000:
        score = 50
    else:
        score = 30

    # Modern format gets a small bonus.
    if _is_modern_format(mime):
        score += 5

    # LCP candidates are more sensitive to being heavy.
    if is_lcp:
        if bytes_ > 600_000:
            score -= 30
        elif bytes_ > 300_000:
            score -= 15
        elif bytes_ > 150_000:
            score -= 5

    # Clamp to [0, 100] and return int.
    if score < 0:
        return 0
    if score > 100:
        return 100
    return int(score)

