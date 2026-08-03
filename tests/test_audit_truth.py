"""
Tests for the audit-truth and redirect-detection guards (Sprint 24).

Closes two production bugs that let the tool lie about the audited page:

1. ``_build_summary`` previously fell into the "All images look well
   optimised" fallback when ``images`` was empty — which is what
   happens on a password-protected Shopify storefront, a JS-error
   page, an auth wall, or any other redirect off-target. The fix
   replaces the fallback with an explicit "No images were extracted"
   message.
2. ``_check_audited_url`` reads ``finalUrl`` / ``finalDisplayedUrl``
   from the Lighthouse JSON and refuses to claim success when the
   page was redirected (exit 10 with a clear error).

Both are pure unit tests — no subprocess, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from engine.audit_orchestrator import _build_summary
from engine.cli import EXIT_LIGHTHOUSE_FAILURE, _check_audited_url, app

runner = CliRunner()


# ---------------------------------------------------------------------------
# _build_summary — empty-images handling
# ---------------------------------------------------------------------------


class TestBuildSummaryEmptyImages:
    """Sprint 24 fix: empty images must NOT trigger the "well optimised"
    fallback. The tool used to lie to the user about zero-image audits
    (e.g. password-protected storefronts)."""

    def test_empty_images_says_no_images_extracted(self) -> None:
        result = _build_summary([])
        assert len(result["top_issues"]) == 1
        assert "No images were extracted" in result["top_issues"][0]
        # The lie is gone.
        assert "All images look well optimised" not in result["top_issues"][0]

    def test_empty_images_does_not_emit_well_optimised_anywhere(self) -> None:
        result = _build_summary([])
        for issue in result["top_issues"]:
            assert "All images look well optimised" not in issue

    def test_with_optimised_images_still_says_well_optimised(self) -> None:
        """Regression guard: a real "well optimised" page still reports it."""
        images: list[dict[str, Any]] = [
            {
                "src": "https://cdn.example.com/hero.jpg",
                "role": "hero",
                "is_lcp_candidate": True,
                "bytes": 50_000,  # well under 300k
                "score": 95,  # above 70
                "mime": "image/webp",
                "waste_bytes_est": 10_000,  # well under 100k
                "displayed_width": 1200,
                "displayed_height": 800,
                "natural_width": 1200,
                "natural_height": 800,
            }
        ]
        result = _build_summary(images)
        assert "All images look well optimised" in result["top_issues"]
        assert "No images were extracted" not in result["top_issues"][0]

    def test_with_oversized_images_still_reports_oversized(self) -> None:
        """Regression guard: the existing oversized-image branch still fires."""
        images: list[dict[str, Any]] = [
            {
                "src": "https://cdn.example.com/big.jpg",
                "role": "hero",
                "is_lcp_candidate": True,
                "bytes": 400_000,
                "score": 95,
                "mime": "image/webp",
                "waste_bytes_est": 200_000,  # well over 100k
                "displayed_width": 1200,
                "displayed_height": 800,
                "natural_width": 1200,
                "natural_height": 800,
            }
        ]
        result = _build_summary(images)
        assert any("byte waste" in issue for issue in result["top_issues"])
        assert "No images were extracted" not in result["top_issues"][0]


# ---------------------------------------------------------------------------
# _check_audited_url — redirect detection
# ---------------------------------------------------------------------------


def _write_lhr(tmp_path: Path, final_url: str | None) -> Path:
    payload: dict[str, Any] = {
        "audits": {},
        "categories": {"performance": {"score": 0.9}},
        "requestedUrl": "https://visualgain.myshopify.com/products/visualgain-image-audit-test-shirt",
    }
    if final_url is not None:
        payload["finalUrl"] = final_url
        payload["finalDisplayedUrl"] = final_url
    path = tmp_path / "lhr.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


REQUESTED = "https://visualgain.myshopify.com/products/visualgain-image-audit-test-shirt"


class TestCheckAuditedUrl:
    """Sprint 24 fix: the CLI must refuse to claim success when Lighthouse
    was redirected off-target. This is the password-storefront case."""

    def test_no_redirect_passes_silently(self, tmp_path: Path) -> None:
        # final == requested → no exit
        json_path = _write_lhr(tmp_path, REQUESTED)
        _check_audited_url(json_path, REQUESTED)  # should not raise

    def test_final_url_missing_passes_silently(self, tmp_path: Path) -> None:
        # Older Lighthouse reports may not include finalUrl at all
        json_path = _write_lhr(tmp_path, None)
        _check_audited_url(json_path, REQUESTED)  # should not raise

    def test_redirect_to_password_exits_10(self, tmp_path: Path) -> None:
        # The exact production failure: storefront password
        json_path = _write_lhr(tmp_path, "https://visualgain.myshopify.com/password")
        with pytest.raises(typer.Exit) as exc:
            _check_audited_url(json_path, REQUESTED)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE

    def test_redirect_to_same_host_404_exits_10(self, tmp_path: Path) -> None:
        # Same host, different path — also a sign of an off-target page
        json_path = _write_lhr(tmp_path, "https://visualgain.myshopify.com/404")
        with pytest.raises(typer.Exit) as exc:
            _check_audited_url(json_path, REQUESTED)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE

    def test_redirect_to_other_host_exits_10(self, tmp_path: Path) -> None:
        # Cross-host redirect: treat as a typo / attack signal
        json_path = _write_lhr(tmp_path, "https://attacker.example/steal")
        with pytest.raises(typer.Exit) as exc:
            _check_audited_url(json_path, REQUESTED)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE

    def test_unparseable_lhr_passes_silently(self, tmp_path: Path) -> None:
        # If the file is corrupt, this helper must not crash — the rest
        # of the pipeline will surface the real parse error.
        bad = tmp_path / "lhr.json"
        bad.write_text("{not json", encoding="utf-8")
        _check_audited_url(bad, REQUESTED)  # should not raise

    def test_unparseable_url_passes_silently(self, tmp_path: Path) -> None:
        # Both URLs are unparseable → cannot compare → pass through.
        json_path = _write_lhr(tmp_path, "not a url")
        _check_audited_url(json_path, "also not a url")  # should not raise

    def test_trailing_slash_is_benign(self, tmp_path: Path) -> None:
        # /products/x -> /products/x/ is a normalising redirect, not an
        # off-target one. Must NOT fail (regression: earlier draft of
        # _check_audited_url was too strict and broke example.com).
        json_path = _write_lhr(tmp_path, REQUESTED + "/")
        _check_audited_url(json_path, REQUESTED)  # should not raise

    def test_fragment_difference_is_benign(self, tmp_path: Path) -> None:
        # Fragment-only changes are always client-side; ignore them.
        json_path = _write_lhr(tmp_path, REQUESTED + "#reviews")
        _check_audited_url(json_path, REQUESTED)  # should not raise

    def test_query_string_difference_is_off_target(self, tmp_path: Path) -> None:
        # Different ?utm_… parameters still represent a different page.
        json_path = _write_lhr(tmp_path, REQUESTED + "?utm_source=test")
        with pytest.raises(typer.Exit) as exc:
            _check_audited_url(json_path, REQUESTED)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE


# ---------------------------------------------------------------------------
# Integration: empty-images end-to-end via CLI
# ---------------------------------------------------------------------------


def _write_empty_images_lhr(tmp_path: Path) -> Path:
    """Lighthouse JSON that extracts to zero images (mirrors the password
    case where ``image-elements`` is absent from the audited page)."""
    payload = {
        "audits": {
            # No image-elements, no resource-summary → extract_images returns []
            "largest-contentful-paint-element": {"details": {"items": []}},
        },
        "categories": {"performance": {"score": 0.9}},
        "requestedUrl": "https://shop.myshopify.com/products/x",
        "finalUrl": "https://shop.myshopify.com/products/x",
        "finalDisplayedUrl": "https://shop.myshopify.com/products/x",
    }
    p = tmp_path / "lhr.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestCliEmptyImagesTruth:
    def test_run_with_lhr_fixtures_never_says_well_optimised_when_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lhr = _write_empty_images_lhr(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["run", "https://shop.myshopify.com/products/x", "--lhr", str(lhr)])
        assert result.exit_code == 0, result.stdout
        # The lie must be gone.
        assert "All images look well optimised" not in result.stdout
        # The truth must be visible.
        assert "No images were extracted" in result.stdout
