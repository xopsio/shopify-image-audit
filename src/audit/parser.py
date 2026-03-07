"""
Lighthouse / fixture JSON parser.
Reads Lighthouse report or fixture JSON and returns normalized image list + LCP candidate (v0.1 heuristic).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalize_image(
    url: str,
    bytes_: int = 0,
    mime: str = "image/jpeg",
    displayed_width: int | None = None,
    displayed_height: int | None = None,
    natural_width: int | None = None,
    natural_height: int | None = None,
    is_lcp_candidate: bool = False,
) -> dict[str, Any]:
    """Build a single normalized image dict (no role/score/recommendation yet)."""
    out: dict[str, Any] = {
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


def _parse_lighthouse_audits(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """
    Parse Lighthouse LHR: extract images and LCP element from audits.
    Returns (normalized_images, lcp_element_url).
    """
    audits = data.get("audits") or {}
    lcp_url: str | None = None

    # LCP element audit (Lighthouse v10+)
    lcp_audit = audits.get("largest-contentful-paint-element")
    if lcp_audit and isinstance(lcp_audit.get("details"), dict):
        details = lcp_audit["details"]
        items = details.get("items") or []
        if items and isinstance(items[0], dict):
            first = items[0]
            if "url" in first:
                lcp_url = first.get("url")
            elif "node" in first and isinstance(first["node"], dict):
                node = first["node"]
                if "url" in node:
                    lcp_url = node.get("url")

    # Image list: try resource summary or network-requests style
    images: list[dict[str, Any]] = []
    seen_src: set[str] = set()

    # Optional: audit that lists image resources (custom or legacy)
    img_audit = audits.get("image-elements") or audits.get("resource-summary")
    if img_audit and isinstance(img_audit.get("details"), dict):
        details = img_audit["details"]
        items = details.get("items") or details.get("nodes") or []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("src")
            if not url or url in seen_src:
                continue
            seen_src.add(url)
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
                    displayed_width=int(dw) if dw is not None else None,
                    displayed_height=int(dh) if dh is not None else None,
                    natural_width=int(nw) if nw is not None else None,
                    natural_height=int(nh) if nh is not None else None,
                    is_lcp_candidate=(url == lcp_url),
                )
            )

    return images, lcp_url


def _parse_fixture_format(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """
    Parse simplified fixture format: { "lcpCandidate": { "url": "..." }, "images": [ ... ] }.
    Returns (normalized_images, lcp_element_url).
    """
    lcp_url: str | None = None
    lcp = data.get("lcpCandidate") or data.get("lcp_candidate")
    if isinstance(lcp, dict) and lcp.get("url"):
        lcp_url = lcp.get("url")

    images: list[dict[str, Any]] = []
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
                displayed_width=int(dw) if dw is not None else None,
                displayed_height=int(dh) if dh is not None else None,
                natural_width=int(nw) if nw is not None else None,
                natural_height=int(nh) if nh is not None else None,
                is_lcp_candidate=(url == lcp_url),
            )
        )
    return images, lcp_url


def parse(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Parse Lighthouse or fixture JSON (already loaded as dict).
    Returns list of normalized images; one may have is_lcp_candidate=True (v0.1 heuristic).
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

    # Lighthouse LHR: has "audits"
    if "audits" in data:
        images, lcp_url = _parse_lighthouse_audits(data)
        if lcp_url and not any(img.get("is_lcp_candidate") for img in images):
            # Ensure LCP candidate exists as an image entry
            images.append(
                _normalize_image(url=lcp_url, bytes_=0, mime="image/jpeg", is_lcp_candidate=True)
            )
        if images:
            return images

    return []


def parse_file(path: str | Path) -> list[dict[str, Any]]:
    """Load JSON from file and return normalized images + LCP candidate marked."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse(data)
