"""
Audit orchestrator – the main pipeline that ties parser → ranker → AuditResult.

Loads LHR / fixture JSON, calls parser and ranker, builds a schema-compliant
AuditResult (validated via Pydantic v2).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.models import AuditResult, ImageRole
from audit.parser import parse
from audit.ranker_heuristic import rank


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_VALID_ROLES = {r.value for r in ImageRole}


def _sanitise_image(img: dict[str, Any]) -> dict[str, Any]:
    """Ensure every image dict is compliant with the schema before validation."""
    out: dict[str, Any] = {}

    out["src"] = img.get("src") or img.get("url") or ""
    out["role"] = img.get("role", "unknown") if img.get("role") in _VALID_ROLES else "unknown"
    out["score"] = max(0, min(100, int(img.get("score", 0))))
    out["bytes"] = max(0, int(img.get("bytes", 0)))
    out["mime"] = img.get("mime") or img.get("mimeType") or "image/jpeg"

    # optional integer fields
    for key in ("displayed_width", "displayed_height", "natural_width", "natural_height", "waste_bytes_est"):
        val = img.get(key)
        if val is not None:
            out[key] = max(0, int(val))

    # optional boolean
    if "is_lcp_candidate" in img:
        out["is_lcp_candidate"] = bool(img["is_lcp_candidate"])

    # optional string
    if "recommendation" in img and img["recommendation"] is not None:
        out["recommendation"] = str(img["recommendation"])

    return out


def _estimate_waste(img: dict[str, Any]) -> int:
    """Rough waste-bytes estimate: difference between actual bytes and a target."""
    bytes_ = img.get("bytes", 0)
    dw = img.get("displayed_width") or img.get("natural_width") or 0
    dh = img.get("displayed_height") or img.get("natural_height") or 0
    area = dw * dh
    if area <= 0:
        return 0
    # target ≈ 0.05 bytes per pixel (aggressive WebP/AVIF estimate)
    target = int(area * 0.05)
    return max(0, bytes_ - target)


def _build_summary(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive top_issues from the ranked image list."""
    issues: list[str] = []

    lcp_imgs = [i for i in images if i.get("is_lcp_candidate")]
    if lcp_imgs:
        lcp = lcp_imgs[0]
        if lcp.get("bytes", 0) > 300_000:
            issues.append(f"LCP image is very large ({lcp['bytes']} bytes) – compress or use modern format")
        elif lcp.get("score", 100) < 70:
            issues.append("LCP image score is below 70 – optimise for faster paint")

    oversized = [i for i in images if _estimate_waste(i) > 100_000]
    if oversized:
        issues.append(f"{len(oversized)} image(s) have significant byte waste (>100 KB estimated)")

    non_modern = [i for i in images if i.get("mime", "").lower() not in ("image/webp", "image/avif", "image/svg+xml")]
    if non_modern:
        issues.append(f"{len(non_modern)} image(s) not using modern format (WebP/AVIF)")

    if not issues:
        issues.append("All images look well optimised")

    return {"top_issues": issues}


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert *value* to float; return *default* on None or conversion failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_vitals(data: dict[str, Any]) -> dict[str, Any]:
    """Best-effort extraction of Web Vitals from LHR or fixture JSON."""
    # Lighthouse LHR stores metrics inside audits.metrics.details.items[0]
    audits = data.get("audits") or {}
    metrics_audit = audits.get("metrics") or {}
    metrics_details = (metrics_audit.get("details") or {}).get("items") or [{}]
    m = metrics_details[0] if metrics_details else {}

    return {
        "lcp_ms": safe_float(m.get("largestContentfulPaint", data.get("lcp_ms"))),
        "cls": safe_float(m.get("cumulativeLayoutShift", data.get("cls"))),
        "inp_ms": safe_float(m.get("interactive", data.get("inp_ms"))),
        "ttfb_ms": safe_float(m.get("serverResponseTime", data.get("ttfb_ms"))),
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def run_audit(
    lhr_path: str | Path,
    *,
    url: str | None = None,
    device: str = "mobile",
    runs: int = 1,
) -> AuditResult:
    """
    Full pipeline: load JSON → parse → rank → validate → AuditResult.

    Parameters
    ----------
    lhr_path : path to a Lighthouse JSON report *or* fixture file.
    url      : override URL for meta; defaults to first image src.
    device   : "mobile" or "desktop".
    runs     : number of Lighthouse runs (informational).

    Returns
    -------
    AuditResult (Pydantic model, schema-compliant).
    """
    lhr_path = Path(lhr_path)

    # 1. load raw JSON
    with open(lhr_path, encoding="utf-8") as f:
        raw: dict[str, Any] = json.load(f)

    # 2. parse → list[dict]  (normalized images, no role/score yet)
    parsed_images: list[dict[str, Any]] = parse(raw)

    # 3. rank  → list[dict]  (role, score, recommendation added)
    ranked_images: list[dict[str, Any]] = rank(parsed_images)

    # 4. add waste estimate & sanitise
    sanitised: list[dict[str, Any]] = []
    for img in ranked_images:
        clean = _sanitise_image(img)
        if "waste_bytes_est" not in clean:
            clean["waste_bytes_est"] = _estimate_waste(clean)
        sanitised.append(clean)

    # 5. build meta
    resolved_url = url or (sanitised[0]["src"] if sanitised else raw.get("requestedUrl", "https://unknown"))
    meta = {
        "url": resolved_url,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device": device,
        "runs": runs,
        "tool": "lighthouse",
    }

    # 6. vitals
    vitals = _extract_vitals(raw)

    # 7. summary
    summary = _build_summary(sanitised)

    # 8. assemble & validate
    payload: dict[str, Any] = {
        "meta": meta,
        "vitals": vitals,
        "images": sanitised,
        "summary": summary,
    }

    return AuditResult.model_validate(payload)

