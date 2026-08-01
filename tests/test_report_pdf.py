"""
Unit + CLI tests for PDF export (Sprint 3, TD-1).

Covers:
- ``render_pdf_report``: produces a valid PDF (>0 bytes, starts with %PDF-)
- PDF resource fetcher: rejects external/file URLs and accepts embedded data
- CLI ``report --pdf`` flag: writes a PDF (default output: report.pdf)
- CLI ``compare --output --pdf``: writes a PDF instead of HTML
- The existing HTML path remains untouched when --pdf is not passed
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib import request

import pytest
from typer.testing import CliRunner

from audit.report import _create_pdf_url_fetcher, render_pdf_report

# Skip the whole module if WeasyPrint can't render — that happens on hosts
# missing system fonts/Pango (e.g. minimal CI images without libpango).
weasyprint = pytest.importorskip("weasyprint")


# ---------------------------------------------------------------------------
# PDF resource fetcher
# ---------------------------------------------------------------------------


class TestPdfUrlFetcher:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.invalid/image.png",
            "https://example.invalid/image.png",
            "file:///etc/passwd",
            "ftp://example.invalid/image.png",
        ],
        ids=["http", "https", "file", "ftp"],
    )
    def test_rejects_non_data_protocols_before_io(
        self,
        url: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_on_io(*args, **kwargs):
            pytest.fail("Fetcher attempted I/O instead of rejecting the URL")

        monkeypatch.setattr(request.OpenerDirector, "open", fail_on_io)
        fetcher = _create_pdf_url_fetcher()

        with pytest.raises(ValueError, match=r"^URI uses disallowed protocol:"):
            fetcher.fetch(url)

    def test_accepts_data_protocol(self) -> None:
        fetcher = _create_pdf_url_fetcher()
        response = fetcher.fetch("data:text/plain;base64,YWxsb3dlZA==")
        try:
            assert response.read() == b"allowed"
        finally:
            response.close()

    def test_render_pdf_report_passes_factory_fetcher_to_weasyprint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = {}
        sentinel_fetcher = object()

        class FakeHTML:
            def __init__(self, *, string, url_fetcher):
                captured["string"] = string
                captured["url_fetcher"] = url_fetcher

            def write_pdf(self, *, target):
                Path(target).write_bytes(b"%PDF")

        monkeypatch.setattr("audit.report._create_pdf_url_fetcher", lambda: sentinel_fetcher)
        monkeypatch.setattr(weasyprint, "HTML", FakeHTML)
        output = tmp_path / "wired.pdf"
        html = "<html><body>safe</body></html>"

        render_pdf_report(html, output)

        assert captured["string"] == html
        assert captured["url_fetcher"] is sentinel_fetcher


# ---------------------------------------------------------------------------
# render_pdf_report (unit)
# ---------------------------------------------------------------------------


class TestRenderPdfReport:
    def test_minimal_html_produces_valid_pdf(self, tmp_path: Path) -> None:
        out = tmp_path / "test.pdf"
        result = render_pdf_report("<html><body><h1>Hello</h1></body></html>", out)
        assert result == out
        assert out.exists()
        data = out.read_bytes()
        assert len(data) > 0
        assert data[:4] == b"%PDF"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deeper" / "test.pdf"
        render_pdf_report("<html></html>", out)
        assert out.exists()

    def test_returns_resolved_path(self, tmp_path: Path) -> None:
        out = tmp_path / "out.pdf"
        result = render_pdf_report("<html></html>", out)
        assert isinstance(result, Path)
        assert result == out

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.pdf"
        out.write_bytes(b"old content")
        render_pdf_report("<html><body>new</body></html>", out)
        # Old content should be gone, replaced with a real PDF
        data = out.read_bytes()
        assert data[:4] == b"%PDF"
        assert b"old content" not in data

    def test_complex_html_with_tables(self, tmp_path: Path) -> None:
        """PDF with the table-heavy report layout — the realistic use case."""
        html = """
        <html><head><style>
        body { font-family: sans-serif; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #333; padding: 8px; text-align: left; }
        .improved { background: #d4edda; }
        .regressed { background: #f8d7da; }
        </style></head><body>
        <h1>Audit Report</h1>
        <table>
            <thead><tr><th>Metric</th><th>Before</th><th>After</th></tr></thead>
            <tbody>
                <tr><td>LCP</td><td>4200ms</td><td class="improved">1800ms</td></tr>
                <tr><td>CLS</td><td>0.18</td><td class="improved">0.04</td></tr>
            </tbody>
        </table>
        </body></html>
        """
        out = tmp_path / "complex.pdf"
        render_pdf_report(html, out)
        data = out.read_bytes()
        assert data[:4] == b"%PDF"
        # Complex layouts produce noticeably bigger files than trivial ones
        assert len(data) > 1000


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def audit_result_file(tmp_path: Path) -> Path:
    """A valid AuditResult JSON for the CLI tests."""
    path = tmp_path / "audit_result.json"
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "url": "https://example.com",
                    "timestamp_utc": "2026-01-01T00:00:00Z",
                    "device": "mobile",
                    "runs": 1,
                    "tool": "lighthouse",
                },
                "vitals": {"lcp_ms": 2500.0, "cls": 0.05, "inp_ms": 150.0, "ttfb_ms": 600.0},
                "images": [
                    {
                        "src": "https://example.com/hero.webp",
                        "role": "hero",
                        "score": 85,
                        "bytes": 95000,
                        "mime": "image/webp",
                        "is_lcp_candidate": True,
                    },
                ],
                "summary": {"top_issues": []},
            }
        )
    )
    return path


class TestReportPdfCli:
    def test_report_pdf_flag_creates_pdf(self, audit_result_file: Path, tmp_path: Path, monkeypatch) -> None:
        from engine.cli import app

        # chdir so the relative -o target is valid (path-safety check).
        monkeypatch.chdir(audit_result_file.parent)

        result = runner.invoke(
            app,
            [
                "report",
                audit_result_file.name,
                "--pdf",
                "-o",
                "report.pdf",
            ],
        )
        assert result.exit_code == 0, result.stdout
        out_pdf = audit_result_file.parent / "report.pdf"
        assert out_pdf.exists()
        assert out_pdf.read_bytes()[:4] == b"%PDF"
        # Cleanup the test artefact so other tests in this dir are unaffected.
        out_pdf.unlink(missing_ok=True)

    def test_report_pdf_default_output_filename(self, audit_result_file: Path, monkeypatch, tmp_path: Path) -> None:
        """With --pdf and no -o, default is report.pdf (not report.html)."""
        from engine.cli import app

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["report", str(audit_result_file), "--pdf"])
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "report.pdf").exists()
        assert not (tmp_path / "report.html").exists()

    def test_report_without_pdf_still_writes_html(self, audit_result_file: Path, tmp_path: Path) -> None:
        """Backward compat: without --pdf, behaviour is unchanged (HTML)."""
        from engine.cli import app

        result = runner.invoke(
            app,
            [
                "report",
                str(audit_result_file),
                "-o",
                str(tmp_path / "report.html"),
            ],
        )
        assert result.exit_code == 0, result.stdout
        html = (tmp_path / "report.html").read_text()
        assert "<!DOCTYPE html>" in html


class TestComparePdfCli:
    def test_compare_pdf_flag_creates_pdf(self, tmp_path: Path, monkeypatch) -> None:
        """``compare --output file.html --pdf`` writes a PDF to that path."""
        from engine.cli import app

        # Workaround for path-safety: chdir into tmp_path so the relative
        # -o target is valid. This mirrors how a customer would run it
        # in their project directory.
        monkeypatch.chdir(tmp_path)

        before = tmp_path / "before.json"
        after = tmp_path / "after.json"
        before.write_text(
            json.dumps(
                {
                    "meta": {
                        "url": "https://b.example",
                        "timestamp_utc": "2026-01-01T00:00:00Z",
                        "device": "mobile",
                        "runs": 1,
                        "tool": "lighthouse",
                    },
                    "vitals": {"lcp_ms": 4200.0, "cls": 0.18, "inp_ms": 320.0, "ttfb_ms": 900.0},
                    "images": [],
                    "summary": {"top_issues": []},
                }
            )
        )
        after.write_text(
            json.dumps(
                {
                    "meta": {
                        "url": "https://a.example",
                        "timestamp_utc": "2026-01-02T00:00:00Z",
                        "device": "mobile",
                        "runs": 1,
                        "tool": "lighthouse",
                    },
                    "vitals": {"lcp_ms": 1800.0, "cls": 0.04, "inp_ms": 180.0, "ttfb_ms": 620.0},
                    "images": [],
                    "summary": {"top_issues": []},
                }
            )
        )

        result = runner.invoke(
            app,
            [
                "compare",
                "before.json",
                "after.json",
                "-o",
                "comparison.pdf",
                "--pdf",
            ],
        )
        assert result.exit_code == 0, result.stdout
        out_pdf = tmp_path / "comparison.pdf"
        assert out_pdf.exists()
        assert out_pdf.read_bytes()[:4] == b"%PDF"

    def test_compare_without_pdf_writes_html(self, tmp_path: Path, monkeypatch) -> None:
        """Backward compat: without --pdf, --output writes HTML."""
        from engine.cli import app

        monkeypatch.chdir(tmp_path)

        before = tmp_path / "b.json"
        after = tmp_path / "a.json"
        before.write_text(
            json.dumps(
                {
                    "meta": {
                        "url": "https://b",
                        "timestamp_utc": "2026-01-01T00:00:00Z",
                        "device": "mobile",
                        "runs": 1,
                        "tool": "lighthouse",
                    },
                    "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
                    "images": [],
                    "summary": {"top_issues": []},
                }
            )
        )
        after.write_text(
            json.dumps(
                {
                    "meta": {
                        "url": "https://a",
                        "timestamp_utc": "2026-01-02T00:00:00Z",
                        "device": "mobile",
                        "runs": 1,
                        "tool": "lighthouse",
                    },
                    "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
                    "images": [],
                    "summary": {"top_issues": []},
                }
            )
        )
        result = runner.invoke(
            app,
            [
                "compare",
                "b.json",
                "a.json",
                "-o",
                "comparison.html",
            ],
        )
        assert result.exit_code == 0, result.stdout
        out_html = tmp_path / "comparison.html"
        assert out_html.exists()
        assert "<!DOCTYPE html>" in out_html.read_text()
