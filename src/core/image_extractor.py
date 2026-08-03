from __future__ import annotations

from typing import Any

from core.image_signals import ImageDict


def _safe_int(value: Any) -> int | None:
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
    """
    Build a single normalized image dict.

    Field names are aligned with the images entries in audit_result.schema.json:
    - required in the final schema: src, bytes, mime, role, score
    - optional: displayed_width/height, natural_width/height, is_lcp_candidate
    This extractor is responsible for the shared image attributes; role/score
    are assigned in later ranking/scoring stages.
    """
    out: ImageDict = {
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


def _extract_lcp_url(lhr: dict[str, Any]) -> str | None:
    """
    Extract LCP element URL from Lighthouse audits (if present).

    Mirrors Lighthouse v10+ `largest-contentful-paint-element` details structure:
    details.items[0].url OR details.items[0].node.url
    """
    audits = lhr.get("audits")
    audits = audits if isinstance(audits, dict) else {}
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


def _collect_from_network_requests(audits: dict[str, Any]) -> dict[str, Any] | None:
    """Synthesise an image-elements-shaped audit from ``network-requests``.

    Lighthouse 13 emits every network record in
    ``audits["network-requests"].details.items`` with a ``resourceType``
    field (e.g. ``"Image"``). When the render-tree audits are empty or
    missing — some pages, fixtures, and Lighthouse plugin configs do
    this — we still want to surface the images that were actually
    loaded over the wire (Sprint 26).

    Returns a dict shaped like the other image audits
    (``{"details": {"items": [...]}}``) so the existing item-parsing
    loop in :func:`_collect_image_items` can read it without changes,
    or ``None`` when no image network records are present.
    """
    nr = audits.get("network-requests")
    if not isinstance(nr, dict):
        return None
    details = nr.get("details")
    if not isinstance(details, dict):
        return None
    items = details.get("items")
    if not isinstance(items, list):
        return None
    image_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Lighthouse 13 emits "Image" (capitalised). The lowercase
        # comparison also accepts "image" in case of plugin variants
        # or future audit renames.
        if str(item.get("resourceType", "")).lower() != "image":
            continue
        image_items.append(item)
    if not image_items:
        return None
    return {"details": {"items": image_items}}


def _collect_image_items(lhr: dict[str, Any]) -> list[ImageDict]:
    """
    Collect raw image resource entries from Lighthouse audits.

    Supports:
    - audits["image-elements"].details.items (preferred — has pixel dims)
    - audits["resource-summary"].details.items / .nodes (fallback)
    - audits["network-requests"].details.items filtered by
      resourceType == "Image" (Sprint 26 — last-resort fallback when
      neither render-tree audit surfaces images; no pixel dims)
    """
    audits = lhr.get("audits")
    audits = audits if isinstance(audits, dict) else {}

    def _has_items(audit: object) -> bool:
        """True if the audit dict contains a non-empty items/nodes list."""
        if not isinstance(audit, dict):
            return False
        details = audit.get("details")
        if not isinstance(details, dict):
            return False
        items = details.get("items") or details.get("nodes")
        return isinstance(items, list) and len(items) > 0

    img_audit: object
    if _has_items(audits.get("image-elements")):
        img_audit = audits["image-elements"]
    elif _has_items(audits.get("resource-summary")):
        img_audit = audits["resource-summary"]
    else:
        img_audit = _collect_from_network_requests(audits)
    if not isinstance(img_audit, dict):
        return []

    details = img_audit.get("details")
    if not isinstance(details, dict):
        return []

    items = details.get("items") or details.get("nodes") or []
    if not isinstance(items, list):
        return []

    result: list[ImageDict] = []
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

        bytes_ = item.get("resourceSize") or item.get("transferSize") or item.get("bytes") or 0
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


def _displayed_area(img: ImageDict) -> int:
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


def _mark_lcp_candidate(images: list[ImageDict], lcp_url: str | None) -> None:
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


def extract_images(lighthouse_json: dict[str, Any]) -> list[ImageDict]:
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
