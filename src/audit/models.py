"""
Pydantic v2 models for Shopify Image Audit – strictly derived from
audit/schemas/audit_result.schema.json (single source of truth).

No extra="allow", no fallbacks, no hacks.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class _ExcludeNoneModel(BaseModel):
    """Base model that omits ``None``-valued optional fields on serialization.

    The JSON schema (``audit/schemas/audit_result.schema.json``) declares optional
    fields as plain ``integer``/``string`` (no ``null``). Pydantic v2 does not
    honour ``exclude_none`` as a ``model_config`` key, so we enable it by
    default at the serialization boundary. ``model_validate`` is unaffected:
    missing keys remain optional and default to ``None``.
    """

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:  # type: ignore[override]
        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(**kwargs)


# ---------- enums ----------

class Device(StrEnum):
    mobile = "mobile"
    desktop = "desktop"


class Tool(StrEnum):
    lighthouse = "lighthouse"


class ImageRole(StrEnum):
    hero = "hero"
    above_fold = "above_fold"
    product_primary = "product_primary"
    product_secondary = "product_secondary"
    decorative = "decorative"
    unknown = "unknown"


# ---------- nested models ----------

class Meta(_ExcludeNoneModel):
    """meta object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    url: str = Field(..., min_length=1)
    timestamp_utc: str = Field(..., min_length=10)
    device: Device
    runs: int = Field(..., ge=1)
    tool: Tool
    notes: str | None = None


class Vitals(_ExcludeNoneModel):
    """vitals object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    lcp_ms: float = Field(..., ge=0)
    cls: float = Field(..., ge=0)
    inp_ms: float = Field(..., ge=0)
    ttfb_ms: float = Field(..., ge=0)


class ImageItem(_ExcludeNoneModel):
    """Single image entry – additionalProperties: false.

    ``exclude_none=True`` is inherited from ``_ExcludeNoneModel`` so
    serialization omits optional fields whose value is None (e.g.
    ``natural_width``). The JSON schema declares these as plain
    ``integer``/``string`` (no ``null``), so emitting ``null`` would violate
    the contract. Round-trip via ``model_validate`` is unaffected: missing keys
    are optional and default to None.
    """
    model_config = {"extra": "forbid"}

    src: str = Field(..., min_length=1)
    role: ImageRole
    score: int = Field(..., ge=0, le=100)
    bytes: int = Field(..., ge=0)
    mime: str = Field(..., min_length=1)
    displayed_width: int | None = Field(default=None, ge=0)
    displayed_height: int | None = Field(default=None, ge=0)
    natural_width: int | None = Field(default=None, ge=0)
    natural_height: int | None = Field(default=None, ge=0)
    is_lcp_candidate: bool | None = None
    waste_bytes_est: int | None = Field(default=None, ge=0)
    recommendation: str | None = None


class Summary(_ExcludeNoneModel):
    """summary object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    top_issues: list[str]


# ---------- top-level ----------

class AuditResult(_ExcludeNoneModel):
    """
    Top-level audit result – maps 1-to-1 to audit_result.schema.json.
    additionalProperties: false
    """
    model_config = {"extra": "forbid"}

    meta: Meta
    vitals: Vitals
    images: list[ImageItem]
    summary: Summary


# ===========================================================================
# Before/After comparison models (Sprint 2, #18 + #20)
#
# These are a SEPARATE data contract from audit_result.schema.json. They
# describe deltas computed by core.baseline_manager.compare() and consumed by
# the `audit compare` CLI command and the HTML report's comparison section.
# Units: ms for LCP/INP/TTFB, unitless for CLS (mirrors the Vitals model).
# ===========================================================================


class MetricDelta(_ExcludeNoneModel):
    """Delta for a single metric (before -> after).

    ``delta`` is ``after - before``: a negative value is an *improvement*
    for LCP/INP/TTFB/CLS (lower is better). ``delta_pct`` is relative to the
    before value (None when before is 0). ``status`` is the derived verdict.
    """
    model_config = {"extra": "forbid"}

    before: float
    after: float
    delta: float
    delta_pct: float | None = None
    status: str = Field(..., pattern="^(improved|regressed|unchanged)$")


class VitalsDelta(_ExcludeNoneModel):
    """Deltas for the Core Web Vitals suite."""
    model_config = {"extra": "forbid"}

    lcp: MetricDelta
    cls: MetricDelta
    inp: MetricDelta
    ttfb: MetricDelta


class ImageStatsDelta(_ExcludeNoneModel):
    """Aggregate image-level changes (cohort level, not per-image)."""
    model_config = {"extra": "forbid"}

    before_count: int = Field(..., ge=0)
    after_count: int = Field(..., ge=0)
    count_delta: int

    before_total_bytes: int = Field(..., ge=0)
    after_total_bytes: int = Field(..., ge=0)
    total_bytes_delta: int

    before_total_waste: int = Field(..., ge=0)
    after_total_waste: int = Field(..., ge=0)
    total_waste_delta: int

    before_avg_score: float = Field(..., ge=0, le=100)
    after_avg_score: float = Field(..., ge=0, le=100)
    avg_score_delta: float


class ComparisonSummary(_ExcludeNoneModel):
    """Human-readable roll-up of a comparison.

    ``recommendations`` is the authoritative, ROI-sorted list of all detected
    changes. ``top_improvements`` and ``top_regressions`` are kept for backward
    compatibility and are derived from ``recommendations`` by the caller.
    """
    model_config = {"extra": "forbid"}

    top_improvements: list[str]
    top_regressions: list[str]
    roi_estimate: str
    recommendations: list[ComparisonRecommendation] = Field(default_factory=list)


class ComparisonRecommendation(_ExcludeNoneModel):
    """A single ROI-ranked recommendation derived from a before/after comparison.

    Each recommendation describes one measurable change (vital metric, image
    payload, score, etc.) and assigns a ``sort_key`` based on estimated
    conversion uplift. Positive ``sort_key`` = improvement; negative = regression.
    The absolute value encodes the estimated ROI magnitude.

    ``estimated_lcp_impact_ms`` is a rough heuristic of how many ms of LCP
    improvement this change likely contributed. It is *not* a measured value.
    """
    model_config = {"extra": "forbid"}

    text: str = Field(..., min_length=1)
    category: str = Field(..., pattern=r"^(lcp|cls|inp|ttfb|image_payload|image_waste|image_score)$")
    estimated_lcp_impact_ms: float = 0.0
    sort_key: float


class ImageDelta(_ExcludeNoneModel):
    """Per-image delta between before and after AuditResults.

    One of ``before`` / ``after`` may be None for added or removed images.
    ``match_key`` identifies which before-image pairs with which after-image
    (see ``core.baseline_manager._image_key`` for the hashing scheme).
    """
    model_config = {"extra": "forbid"}

    match_key: str
    src: str
    role_before: str | None = None
    role_after: str | None = None

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    bytes_delta: int | None = None
    score_delta: int | None = None
    mime_before: str | None = None
    mime_after: str | None = None

    status: str = Field(
        ..., pattern="^(improved|regressed|unchanged|added|removed)$"
    )

    recommendation: str | None = None


class ComparisonResult(_ExcludeNoneModel):
    """Top-level result of comparing two AuditResults.

    ``before_meta`` / ``after_meta`` keep just the identifying metadata (url,
    timestamp) so the report can label the two sides without carrying full
    AuditResults around.
    """
    model_config = {"extra": "forbid"}

    before: dict[str, str]
    after: dict[str, str]
    vitals: VitalsDelta
    images: ImageStatsDelta
    summary: ComparisonSummary
    per_image: list[ImageDelta] = Field(default_factory=list)

