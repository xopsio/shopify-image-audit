"""
Pydantic v2 models for Shopify Image Audit – strictly derived from
schemas/audit_result.schema.json (single source of truth).

No extra="allow", no fallbacks, no hacks.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class _ExcludeNoneModel(BaseModel):
    """Base model that omits ``None``-valued optional fields on serialization.

    The JSON schema (``schemas/audit_result.schema.json``) declares optional
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

class Device(str, Enum):
    mobile = "mobile"
    desktop = "desktop"


class Tool(str, Enum):
    lighthouse = "lighthouse"


class ImageRole(str, Enum):
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
    notes: Optional[str] = None


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
    displayed_width: Optional[int] = Field(default=None, ge=0)
    displayed_height: Optional[int] = Field(default=None, ge=0)
    natural_width: Optional[int] = Field(default=None, ge=0)
    natural_height: Optional[int] = Field(default=None, ge=0)
    is_lcp_candidate: Optional[bool] = None
    waste_bytes_est: Optional[int] = Field(default=None, ge=0)
    recommendation: Optional[str] = None


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
