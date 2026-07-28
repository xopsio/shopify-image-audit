"""
Integrations module for Shopify Image Audit.

Contains external API clients and service integrations.
"""

from __future__ import annotations

from integrations.pagespeed_api import (
    PageSpeedAPIClient,
    PageSpeedMetrics,
    get_pagespeed_metrics,
)

__all__ = [
    "PageSpeedAPIClient",
    "PageSpeedMetrics",
    "get_pagespeed_metrics",
]
