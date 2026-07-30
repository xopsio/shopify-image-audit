"""
Unit tests for ``src/engine/cli_helpers/_errors.py``.

The decorators convert exceptions raised inside the wrapped function into
clean ``typer.Exit`` codes. They preserve the original exception via
``raise ... from exc`` so callers can still inspect the cause.
"""

from __future__ import annotations

import json

import pytest
from typer import Exit

from engine.cli_helpers._errors import (
    handle_compare_errors,
    handle_json_errors,
    handle_pipeline_errors,
)

# ---------------------------------------------------------------------------
# handle_json_errors
# ---------------------------------------------------------------------------

class TestHandleJsonErrors:
    def test_happy_path_returns_value(self, tmp_path) -> None:
        path = tmp_path / "ok.json"
        path.write_text('{"a": 1}')

        @handle_json_errors(str(path))
        def load():
            return json.loads(path.read_text())

        assert load() == {"a": 1}

    def test_json_error_raises_exit_2(self, tmp_path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")

        @handle_json_errors(str(path))
        def load():
            return json.loads(path.read_text())

        with pytest.raises(Exit) as exc:
            load()
        assert exc.value.exit_code == 2

    def test_preserves_original_exception_via_from(self, tmp_path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json")

        @handle_json_errors(str(path))
        def load():
            return json.loads(path.read_text())

        with pytest.raises(Exit) as exc:
            load()
        assert isinstance(exc.value.__cause__, json.JSONDecodeError)

    def test_other_exceptions_propagate_unchanged(self, tmp_path) -> None:
        path = tmp_path / "x.json"

        @handle_json_errors(str(path))
        def boom():
            raise RuntimeError("not a JSON error")

        with pytest.raises(RuntimeError, match="not a JSON error"):
            boom()


# ---------------------------------------------------------------------------
# handle_pipeline_errors
# ---------------------------------------------------------------------------

class TestHandlePipelineErrors:
    def test_happy_path(self) -> None:
        @handle_pipeline_errors(step_name="audit")
        def run():
            return "ok"

        assert run() == "ok"

    @pytest.mark.parametrize("exc_cls,msg", [
        (FileNotFoundError, "missing"),
        (ValueError, "bad input"),
    ])
    def test_input_errors_become_exit_2(self, exc_cls, msg) -> None:
        @handle_pipeline_errors(step_name="audit")
        def run():
            raise exc_cls(msg)

        with pytest.raises(Exit) as exc:
            run()
        assert exc.value.exit_code == 2

    def test_runtime_error_becomes_exit_10(self) -> None:
        """RuntimeError -> 10 (backend / API failure convention)."""

        @handle_pipeline_errors(step_name="audit")
        def run():
            raise RuntimeError("API down")

        with pytest.raises(Exit) as exc:
            run()
        assert exc.value.exit_code == 10

    def test_unknown_error_uses_unknown_exit_code(self) -> None:
        @handle_pipeline_errors(step_name="audit", unknown_exit_code=99)
        def run():
            raise KeyError("weird")

        with pytest.raises(Exit) as exc:
            run()
        assert exc.value.exit_code == 99

    def test_default_unknown_exit_code_is_2(self) -> None:
        @handle_pipeline_errors(step_name="audit")
        def run():
            raise KeyError("weird")

        with pytest.raises(Exit) as exc:
            run()
        assert exc.value.exit_code == 2

    def test_preserves_original_exception_via_from(self) -> None:
        @handle_pipeline_errors(step_name="audit")
        def run():
            raise ValueError("original")

        with pytest.raises(Exit) as exc:
            run()
        assert isinstance(exc.value.__cause__, ValueError)


# ---------------------------------------------------------------------------
# handle_compare_errors
# ---------------------------------------------------------------------------

class TestHandleCompareErrors:
    def test_happy_path(self) -> None:
        @handle_compare_errors()
        def cmp():
            return "ok"

        assert cmp() == "ok"

    @pytest.mark.parametrize("exc", [
        json.JSONDecodeError("bad json", "x.json", 5),
        ValueError("bad input"),
        FileNotFoundError("missing.json"),
    ])
    def test_input_errors_become_exit_2(self, exc) -> None:
        @handle_compare_errors()
        def cmp():
            raise exc

        with pytest.raises(Exit) as exc_info:
            cmp()
        assert exc_info.value.exit_code == 2

    def test_filenotfound_becomes_exit_2(self) -> None:
        @handle_compare_errors()
        def cmp():
            raise FileNotFoundError("x.json")

        with pytest.raises(Exit) as exc:
            cmp()
        assert exc.value.exit_code == 2

    def test_runtime_error_becomes_exit_10(self) -> None:
        """RuntimeError -> 10 (backend / API failure)."""

        @handle_compare_errors()
        def cmp():
            raise RuntimeError("API down")

        with pytest.raises(Exit) as exc:
            cmp()
        assert exc.value.exit_code == 10

    def test_generic_exception_becomes_exit_2(self) -> None:
        @handle_compare_errors()
        def cmp():
            raise KeyError("unexpected")

        with pytest.raises(Exit) as exc:
            cmp()
        assert exc.value.exit_code == 2

    def test_preserves_original_exception_via_from(self) -> None:
        @handle_compare_errors()
        def cmp():
            raise RuntimeError("API down")

        with pytest.raises(Exit) as exc:
            cmp()
        assert isinstance(exc.value.__cause__, RuntimeError)
