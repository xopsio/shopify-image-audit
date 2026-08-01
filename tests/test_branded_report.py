"""
Unit tests for the brand customisation helpers and the integration of
brand parameters into ``generate_html_report`` / ``write_html_report``
(Sprint 4, TD-2).

The report remains backward-compatible: callers that don't pass brand
parameters get the same HTML as before (verified by the existing
``test_report.py`` suite).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from audit.report import (
    _parse_brand_color,
    _read_brand_logo,
    generate_html_report,
    write_html_report,
)

# ---------------------------------------------------------------------------
# _parse_brand_color
# ---------------------------------------------------------------------------


class TestParseBrandColor:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("#fff", "#ffffff"),
            ("#FFF", "#ffffff"),
            ("#ff6b35", "#ff6b35"),
            ("#FF6B35", "#ff6b35"),
            ("#1234AB", "#1234ab"),
            ("  #ff6b35  ", "#ff6b35"),
        ],
    )
    def test_accepts_valid(self, raw: str, expected: str) -> None:
        assert _parse_brand_color(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "ff6b35",  # missing #
            "#ff",  # wrong length
            "#fffff",  # wrong length
            "#ff6b3z",  # non-hex char
            "red",  # named colour
            "#ff6b3555",  # 8-char hex (RGBA, not supported)
        ],
    )
    def test_rejects_invalid(self, raw: str | None) -> None:
        assert _parse_brand_color(raw) is None


# ---------------------------------------------------------------------------
# _read_brand_logo
# ---------------------------------------------------------------------------


class TestReadBrandLogo:
    def test_reads_png(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-png-data")
        result = _read_brand_logo(logo)
        assert result is not None
        mime, b64 = result
        assert mime == "image/png"
        assert base64.b64decode(b64) == logo.read_bytes()

    def test_reads_jpg(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.jpg"
        logo.write_bytes(b"\xff\xd8\xff" + b"fake-jpg-data")
        result = _read_brand_logo(logo)
        assert result is not None
        assert result[0] == "image/jpeg"

    def test_reads_jpeg_extension(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.jpeg"
        logo.write_bytes(b"\xff\xd8\xff" + b"data")
        result = _read_brand_logo(logo)
        assert result is not None
        assert result[0] == "image/jpeg"

    def test_reads_svg(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.svg"
        logo.write_bytes(b"<svg></svg>")
        result = _read_brand_logo(logo)
        assert result is not None
        assert result[0] == "image/svg+xml"

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        assert _read_brand_logo(tmp_path / "missing.png") is None

    def test_rejects_unsupported_extension(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.bmp"
        logo.write_bytes(b"fake-bmp")
        assert _read_brand_logo(logo) is None

    def test_rejects_oversized_file(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.png"
        # 6 MB > 5 MB cap
        logo.write_bytes(b"\x89PNG" + b"x" * (6 * 1024 * 1024))
        assert _read_brand_logo(logo) is None

    def test_rejects_directory(self, tmp_path: Path) -> None:
        # Directories aren't files; stat() succeeds but is_file() fails.
        assert _read_brand_logo(tmp_path) is None

    def test_svg_with_script_tag_rejected(self, tmp_path: Path) -> None:
        """Basic injection guard: SVGs containing <script> are rejected.

        This is a cheap tripwire, not a full SVG sanitiser. It catches the
        common "external SVG with embedded JS" case.
        """
        logo = tmp_path / "evil.svg"
        logo.write_bytes(b"<svg><script>alert(1)</script></svg>")
        assert _read_brand_logo(logo) is None

    def test_svg_with_lowercase_script_rejected(self, tmp_path: Path) -> None:
        """Match is case-insensitive (the data-URI HTML is rendered into a
        browser that doesn't care about element-name case)."""
        logo = tmp_path / "evil.svg"
        logo.write_bytes(b"<svg><SCRIPT>alert(1)</SCRIPT></svg>")
        assert _read_brand_logo(logo) is None


# ---------------------------------------------------------------------------
# generate_html_report — brand integration
# ---------------------------------------------------------------------------


def _minimal_audit_result() -> dict:
    return {
        "meta": {
            "url": "https://example.com",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "device": "mobile",
            "runs": 1,
            "tool": "lighthouse",
        },
        "vitals": {"lcp_ms": 1000.0, "cls": 0.05, "inp_ms": 100.0, "ttfb_ms": 200.0},
        "images": [
            {"src": "https://x/a.jpg", "role": "hero", "score": 85, "bytes": 50000, "mime": "image/jpeg"},
        ],
        "summary": {"top_issues": []},
    }


class TestGenerateHtmlReportBranding:
    def test_no_branding_default_render(self) -> None:
        """Without brand args, the report renders the same as before.

        Verifies the new parameters don't break the existing layout.
        """
        html = generate_html_report(_minimal_audit_result())
        assert "<!DOCTYPE html>" in html
        assert "Shopify Image Audit Report" in html
        assert "data:image" not in html  # no logo
        assert ":root {" not in html or "var(--brand-color" not in html

    def test_brand_logo_embedded_as_data_uri(self, tmp_path: Path) -> None:
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"\x89PNG" + b"data")
        html = generate_html_report(
            _minimal_audit_result(),
            brand_logo=_read_brand_logo(logo),
        )
        expected_b64 = base64.b64encode(logo.read_bytes()).decode("ascii")
        assert f"data:image/png;base64,{expected_b64}" in html
        assert 'class="brand-logo"' in html

    def test_brand_color_creates_css_variable(self) -> None:
        html = generate_html_report(
            _minimal_audit_result(),
            brand_color="#ff6b35",
        )
        assert ":root { --brand-color: #ff6b35; }" in html
        # The actual rule uses the variable.
        assert "var(--brand-color" in html

    def test_invalid_brand_color_falls_back(self) -> None:
        """Invalid colour -> report still renders, no CSS variable.

        This tests the *recommended* call pattern: validate the colour
        with ``_parse_brand_color`` first, then pass the (possibly None)
        result to ``generate_html_report``.
        """
        raw = "not-a-colour"
        validated = _parse_brand_color(raw)
        assert validated is None  # confirm the validator rejects it
        html = generate_html_report(
            _minimal_audit_result(),
            brand_color=validated,
        )
        # The CSS variable line is omitted; the fallback value in the
        # var(--brand-color, #3498db) is still used.
        assert ":root { --brand-color" not in html
        assert "var(--brand-color" in html  # fallback still works

    def test_no_logo_means_no_img_tag(self) -> None:
        html = generate_html_report(
            _minimal_audit_result(),
            brand_color="#ff6b35",
        )
        assert "<img" not in html
        assert 'class="brand-logo"' not in html


# ---------------------------------------------------------------------------
# write_html_report — brand integration
# ---------------------------------------------------------------------------


class TestWriteHtmlReportBranding:
    def test_brand_persists_through_io(self, tmp_path: Path) -> None:
        # End-to-end: JSON in -> branded HTML out.
        json_path = tmp_path / "audit.json"
        json_path.write_text(json.dumps(_minimal_audit_result()))
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"\x89PNG" + b"x")

        out_path = tmp_path / "report.html"
        write_html_report(
            json_path,
            out_path,
            brand_logo=logo,
            brand_color="#ff6b35",
        )

        html = out_path.read_text(encoding="utf-8")
        assert f"data:image/png;base64,{base64.b64encode(logo.read_bytes()).decode()}" in html
        assert ":root { --brand-color: #ff6b35; }" in html

    def test_missing_logo_file_silently_skipped(self, tmp_path: Path) -> None:
        """Missing logo file -> no logo in report, no error."""
        json_path = tmp_path / "audit.json"
        json_path.write_text(json.dumps(_minimal_audit_result()))
        out_path = tmp_path / "report.html"
        # No logo path passed — just verify the default still works.
        write_html_report(json_path, out_path)
        html = out_path.read_text(encoding="utf-8")
        assert "<img" not in html
        assert "<!DOCTYPE html>" in html

    def test_invalid_colour_silently_falls_back(self, tmp_path: Path) -> None:
        json_path = tmp_path / "audit.json"
        json_path.write_text(json.dumps(_minimal_audit_result()))
        out_path = tmp_path / "report.html"
        write_html_report(json_path, out_path, brand_color="zzz")
        html = out_path.read_text(encoding="utf-8")
        # No :root block with --brand-color; the default fallback applies.
        assert ":root { --brand-color" not in html
