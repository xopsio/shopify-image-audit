"""
Lighthouse / fixture JSON parser (thin wrapper).

Routes input by format and delegates to the canonical implementations:
- Lighthouse LHR (has ``audits``) -> ``core.image_extractor.extract_images``
- Simplified fixture format (has ``images`` / ``lcpCandidate``) -> handled here.

This module is the public parsing API used by the orchestrator and CLI.
The Lighthouse normalization + LCP marking logic lives in
``core.image_extractor`` (single source of truth, governance v1.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.image_extractor import extract_images
from core.image_signals import ImageDict


def safe_int(value: Any) -> int | None:
    """Convert value to int safely; return None if conversion fails."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_image(
    url: str,
    bytes_: int = 0,
    mime: str = "image/jpeg",
    displayed_width: int | None = None,
    displayed_height: int | None = None,
    natural_width: int | None = None,
    natural_height: int | None = None,
    is_lcp_candidate: bool = False,
) -> ImageDict:
    """Build a single normalized image dict (no role/score/recommendation yet).

    Kept for the simplified fixture format path so output stays byte-for-byte
    compatible with previous behaviour; the Lighthouse path now shares
    ``core.image_extractor``'s implementation.
    """
    out: ImageDict = {
        "src": url,
        "bytes": bytes_,
        "mime": mime,
        "is_lcp_candidate": is_lcp_candidate,
    }
    if displayed_width is not None:
        out["displayed_width"] = displayed_width
    if displayed_height is not None:
        out["displayed_height"] = displayed_height
    if natural_width is not None:
        out["natural_width"] = natural_width
    if natural_height is not None:
        out["natural_height"] = natural_height
    return out


def _parse_fixture_format(data: dict[str, Any]) -> tuple[list[ImageDict], str | None]:
    """
    Parse simplified fixture format: { "lcpCandidate": { "url": "..." }, "images": [ ... ] }.
    Returns (normalized_images, lcp_element_url).
    """
    lcp_url: str | None = None
    lcp = data.get("lcpCandidate") or data.get("lcp_candidate")
    if isinstance(lcp, dict) and lcp.get("url"):
        lcp_url = lcp.get("url")

    images: list[ImageDict] = []
    raw_images = data.get("images") or data.get("resources") or []
    for item in raw_images:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("src")
        if not url:
            continue
        bytes_ = int(item.get("resourceSize") or item.get("transferSize") or item.get("bytes") or 0)
        mime = str(item.get("mimeType") or item.get("mime") or "image/jpeg")
        dw = item.get("displayedWidth") or item.get("displayed_width")
        dh = item.get("displayedHeight") or item.get("displayed_height")
        nw = item.get("naturalWidth") or item.get("natural_width")
        nh = item.get("naturalHeight") or item.get("natural_height")
        images.append(
            _normalize_image(
                url=url,
                bytes_=bytes_,
                mime=mime,
                displayed_width=safe_int(dw),
                displayed_height=safe_int(dh),
                natural_width=safe_int(nw),
                natural_height=safe_int(nh),
                is_lcp_candidate=(url == lcp_url),
            )
        )
    return images, lcp_url


def parse(data: dict[str, Any]) -> list[ImageDict]:
    """
    Parse Lighthouse or fixture JSON (already loaded as dict).
    Returns list of normalized images; one may have is_lcp_candidate=True (v0.1 heuristic).

    Format routing:
    - Simplified fixture format (has ``images`` / ``lcpCandidate``) -> local parser.
    - Lighthouse LHR (has ``audits``) -> ``core.image_extractor.extract_images``.
    """
    # Fixture format: has "images" or "lcpCandidate" at top level
    if "images" in data or "lcp_candidate" in data or "lcpCandidate" in data:
        images, lcp_url = _parse_fixture_format(data)
        if lcp_url and not any(img.get("is_lcp_candidate") for img in images):
            images.append(
                _normalize_image(url=lcp_url, bytes_=0, mime="image/jpeg", is_lcp_candidate=True)
            )
        if images:
            return images

    # Lighthouse LHR: delegate to core.image_extractor (single source of truth).
    if "audits" in data:
        images = extract_images(data)
        if images:
            return images

    return []


def parse_file(path: str | Path) -> list[ImageDict]:
    """Load JSON from file and return normalized images + LCP candidate marked."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse(data)
