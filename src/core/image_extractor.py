from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe_int(value: Any) -> Optional[int]:
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
    displayed_width: Optional[int] = None,
    displayed_height: Optional[int] = None,
    natural_width: Optional[int] = None,
    natural_height: Optional[int] = None,
    is_lcp_candidate: bool = False,
) -> Dict[str, Any]:
    """
    Build a single normalized image dict.

    Field names are aligned with the images entries in audit_result.schema.json:
    - required in the final schema: src, bytes, mime, role, score
    - optional: displayed_width/height, natural_width/height, is_lcp_candidate
    This extractor is responsible for the shared image attributes; role/score
    are assigned in later ranking/scoring stages.
    """
    out: Dict[str, Any] = {
        "src": url,
        "bytes": int(bytes_) if bytes_ is not None else 0,
        "mime": mime,
        "is_lcp_candidate": bool(is_lcp_candidate),
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


def _extract_lcp_url(lhr: Dict[str, Any]) -> Optional[str]:
    """
    Extract LCP element URL from Lighthouse audits (if present).

    Mirrors Lighthouse v10+ `largest-contentful-paint-element` details structure:
    details.items[0].url OR details.items[0].node.url
    """
    audits = lhr.get("audits") or {}
    lcp_audit = audits.get("largest-contentful-paint-element")
    if not isinstance(lcp_audit, dict):
        return None

    details = lcp_audit.get("details")
    if not isinstance(details, dict):
        return None

    items = details.get("items") or []
    if not items or not isinstance(items, list):
        return None

    first = items[0]
    if not isinstance(first, dict):
        return None

    if "url" in first and first.get("url"):
        return str(first.get("url"))

    node = first.get("node")
    if isinstance(node, dict) and node.get("url"):
        return str(node.get("url"))

    return None


def _collect_image_items(lhr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Collect raw image resource entries from Lighthouse audits.

    Supports:
    - audits["image-elements"].details.items
    - audits["resource-summary"].details.items / .nodes
    """
    audits = lhr.get("audits") or {}
    img_audit = audits.get("image-elements") or audits.get("resource-summary")
    if not isinstance(img_audit, dict):
        return []

    details = img_audit.get("details")
    if not isinstance(details, dict):
        return []

    items = details.get("items") or details.get("nodes") or []
    if not isinstance(items, list):
        return []

    result: List[Dict[str, Any]] = []
    seen_src: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        url = item.get("url") or item.get("src")
        if not url:
            continue

        url_str = str(url)
        if url_str in seen_src:
            continue
        seen_src.add(url_str)

        bytes_ = (
            item.get("resourceSize")
            or item.get("transferSize")
            or item.get("bytes")
            or 0
        )
        mime = item.get("mimeType") or item.get("mime") or "image/jpeg"
        dw = item.get("displayedWidth") or item.get("displayed_width")
        dh = item.get("displayedHeight") or item.get("displayed_height")
        nw = item.get("naturalWidth") or item.get("natural_width")
        nh = item.get("naturalHeight") or item.get("natural_height")

        result.append(
            _normalize_image(
                url=url_str,
                bytes_=int(bytes_ or 0),
                mime=str(mime),
                displayed_width=_safe_int(dw),
                displayed_height=_safe_int(dh),
                natural_width=_safe_int(nw),
                natural_height=_safe_int(nh),
                is_lcp_candidate=False,  # marked in a separate pass
            )
        )

    return result


def _displayed_area(img: Dict[str, Any]) -> int:
    """Displayed pixel area; 0 if dimensions missing."""
    w = img.get("displayed_width") or img.get("natural_width") or 0
    h = img.get("displayed_height") or img.get("natural_height") or 0
    try:
        w_int = int(w)
        h_int = int(h)
    except (TypeError, ValueError):
        return 0
    if w_int <= 0 or h_int <= 0:
        return 0
    return w_int * h_int


def _mark_lcp_candidate(images: List[Dict[str, Any]], lcp_url: Optional[str]) -> None:
    """
    Mutate images in-place to set is_lcp_candidate using:
    1) Exact URL match if lcp_url is provided.
    2) Fallback: largest displayed area; if all areas are zero, first image.
    """
    if not images:
        return

    marked = False
    if lcp_url:
        for img in images:
            if img.get("src") == lcp_url:
                img["is_lcp_candidate"] = True
                marked = True
            else:
                img["is_lcp_candidate"] = bool(img.get("is_lcp_candidate", False))

    if marked:
        return

    # Fallback heuristics: choose the largest above-the-fold style image
    best_index = 0
    best_area = -1
    for idx, img in enumerate(images):
        area = _displayed_area(img)
        if area > best_area:
            best_area = area
            best_index = idx

    images[best_index]["is_lcp_candidate"] = True


def extract_images(lighthouse_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract normalized image dicts from a Lighthouse JSON report.

    - Input: full Lighthouse LHR (dict), typically parsed from lighthouse JSON.
    - Output: list of dicts using audit_result.schema.json image field names:
      src, bytes, mime, optional displayed_* / natural_*, and is_lcp_candidate.

    Role and score are not assigned here; they belong to higher-level ranking
    and scoring components.
    """
    if not isinstance(lighthouse_json, dict):
        return []

    # Require Lighthouse audits structure; otherwise return empty list.
    if "audits" not in lighthouse_json:
        return []

    lcp_url = _extract_lcp_url(lighthouse_json)
    images = _collect_image_items(lighthouse_json)
    if not images:
        return []

    _mark_lcp_candidate(images, lcp_url)
    return images

