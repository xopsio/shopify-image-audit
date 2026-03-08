"""
Pydantic v2 models for Shopify Image Audit – strictly derived from
schemas/audit_result.schema.json (single source of truth).

No extra="allow", no fallbacks, no hacks.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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

class Meta(BaseModel):
    """meta object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    url: str = Field(..., min_length=1)
    timestamp_utc: str = Field(..., min_length=10)
    device: Device
    runs: int = Field(..., ge=1)
    tool: Tool
    notes: Optional[str] = None


class Vitals(BaseModel):
    """vitals object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    lcp_ms: float = Field(..., ge=0)
    cls: float = Field(..., ge=0)
    inp_ms: float = Field(..., ge=0)
    ttfb_ms: float = Field(..., ge=0)


class ImageItem(BaseModel):
    """Single image entry – additionalProperties: false"""
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


class Summary(BaseModel):
    """summary object – additionalProperties: false"""
    model_config = {"extra": "forbid"}

    top_issues: list[str]


# ---------- top-level ----------

class AuditResult(BaseModel):
    """
    Top-level audit result – maps 1-to-1 to audit_result.schema.json.
    additionalProperties: false
    """
    model_config = {"extra": "forbid"}

    meta: Meta
    vitals: Vitals
    images: list[ImageItem]
    summary: Summary

