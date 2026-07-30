"""
Unit tests for ``src/engine/cli_helpers/_validators.py``.

Covers all path/URL validation primitives extracted from the monolithic
``cli.py`` during the #21 refactor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer import Exit

from engine.cli_helpers._validators import (
    _is_windows_absolute_path,
    require_exists,
    validate_measure_url,
    validate_out_path,
    validate_run_url,
    validate_url_scheme,
)

# ---------------------------------------------------------------------------
# _is_windows_absolute_path
# ---------------------------------------------------------------------------

class TestIsWindowsAbsolutePath:
    """The detection function only activates on Windows; on Linux/macOS it
    always returns False regardless of input shape."""

    def test_returns_false_on_posix_for_unix_path(self) -> None:
        if not _is_windows_absolute_path.__module__:  # smoke; logic is posix-dependent
            pass
        # On any non-Windows runtime the function must short-circuit to False.
        import os
        if os.name != "nt":
            assert _is_windows_absolute_path("/usr/local/bin") is False
            assert _is_windows_absolute_path("C:\\foo") is False  # even if it looks Windows


# ---------------------------------------------------------------------------
# validate_out_path
# ---------------------------------------------------------------------------

class TestValidateOutPath:
    def test_relative_path_returned_as_path(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = validate_out_path("subdir/file.html")
        assert result == Path("subdir/file.html")

    def test_absolute_path_rejected(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exit) as exc:
            validate_out_path("/abs/path.html")
        assert exc.value.exit_code == 2

    def test_dotdot_rejected(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exit) as exc:
            validate_out_path("../escape.html")
        assert exc.value.exit_code == 2

    def test_traversal_in_middle_rejected(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exit) as exc:
            validate_out_path("a/../../etc/passwd")
        assert exc.value.exit_code == 2

    def test_resolve_outside_cwd_rejected(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        # Create a sibling dir; path that resolves outside cwd.
        sibling = tmp_path.parent / "sibling"
        sibling.mkdir(exist_ok=True)
        with pytest.raises(Exit) as exc:
            # Use a path that contains .. which resolves outside cwd
            validate_out_path("../sibling/file.html")
        assert exc.value.exit_code == 2

    def test_label_parameter_used_in_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exit):
            validate_out_path("/abs", label="--my-flag")
        # No way to inspect rich.print output here without redirecting; we
        # only verify the exit code, not the message content.

    def test_accepts_path_object(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = validate_out_path(Path("foo/bar.txt"))
        assert isinstance(result, Path)
        assert result == Path("foo/bar.txt")


# ---------------------------------------------------------------------------
# require_exists
# ---------------------------------------------------------------------------

class TestRequireExists:
    def test_existing_file_returns_path(self, tmp_path: Path) -> None:
        p = tmp_path / "exists.txt"
        p.write_text("hi")
        result = require_exists(p)
        assert result == p

    def test_missing_file_exits_2(self, tmp_path: Path) -> None:
        with pytest.raises(Exit) as exc:
            require_exists(tmp_path / "missing.txt")
        assert exc.value.exit_code == 2

    def test_accepts_string(self, tmp_path: Path) -> None:
        p = tmp_path / "exists.txt"
        p.write_text("hi")
        result = require_exists(str(p))
        assert result == p

    def test_custom_label_does_not_raise_extra(self, tmp_path: Path) -> None:
        """The label affects the error message but not the exit code."""
        with pytest.raises(Exit) as exc:
            require_exists(tmp_path / "missing.json", label="baseline file")
        assert exc.value.exit_code == 2


# ---------------------------------------------------------------------------
# validate_url_scheme / validate_run_url / validate_measure_url
# ---------------------------------------------------------------------------

class TestValidateRunUrl:
    @pytest.mark.parametrize("url", [
        "https://example.com",
        "http://example.com",
        "https://example.com/path?q=1",
    ])
    def test_accepts_http_and_https(self, url: str) -> None:
        validate_run_url(url)  # must not raise

    @pytest.mark.parametrize("url", [
        "ftp://example.com",
        "example.com",
        "",
        "javascript:alert(1)",
    ])
    def test_rejects_invalid_scheme(self, url: str) -> None:
        with pytest.raises(Exit) as exc:
            validate_run_url(url)
        assert exc.value.exit_code == 2


class TestValidateMeasureUrl:
    """Same as run, but allows scheme-less inputs (PageSpeed normalizes)."""

    def test_accepts_http_and_https(self) -> None:
        validate_measure_url("https://example.com")
        validate_measure_url("http://example.com")

    def test_accepts_scheme_less(self) -> None:
        validate_measure_url("example.com")
        validate_measure_url("demo.myshopify.com")

    def test_rejects_explicit_bad_scheme(self) -> None:
        with pytest.raises(Exit) as exc:
            validate_measure_url("ftp://example.com")
        assert exc.value.exit_code == 2

    def test_rejects_https_no_hostname(self) -> None:
        with pytest.raises(Exit) as exc:
            validate_measure_url("https://")
        assert exc.value.exit_code == 2

    def test_rejects_empty(self) -> None:
        with pytest.raises(Exit) as exc:
            validate_measure_url("")
        assert exc.value.exit_code == 2


class TestValidateUrlSchemeDirect:
    def test_run_mode_rejects_scheme_less(self) -> None:
        # When allow_scheme_less=False, scheme-less is rejected
        with pytest.raises(Exit):
            validate_url_scheme("example.com", allow_scheme_less=False)

    def test_measure_mode_accepts_scheme_less_with_netloc(self) -> None:
        # When allow_scheme_less=True, scheme-less is allowed if it has a netloc.
        validate_url_scheme("example.com", allow_scheme_less=True)

    def test_measure_mode_rejects_truly_empty(self) -> None:
        """An empty string with allow_scheme_less=True still fails."""
        with pytest.raises(Exit):
            validate_url_scheme("", allow_scheme_less=True)
