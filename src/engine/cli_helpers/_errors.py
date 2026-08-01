"""
CLI error-handling decorators.

Wrap a step function to convert a well-known exception into a clean
``typer.Exit`` with a red error line and a fixed exit code. Used by command
bodies to eliminate the ``try: ... except SomeError: rprint(...); raise Exit(...)``
boilerplate that was duplicated across every command.

Usage::

    @handle_json_errors(input_path)
    def load_audit_result(input_path: str) -> dict:
        with open(input_path) as f:
            return json.load(f)

The wrapped function still raises the original exception (via ``from``); the
decorator only intercepts the *display* of the exception as a CLI exit.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich import print as rprint


def handle_json_errors(input_path: str | Path) -> Callable:
    """Convert ``json.JSONDecodeError`` into exit-2 with a clear message.

    Args:
        input_path: the file path being read (used in the error message).
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from typer import Exit

            try:
                return func(*args, **kwargs)
            except json.JSONDecodeError as exc:
                rprint(f"[red]Error:[/red] Invalid JSON in {input_path}: {exc}")
                raise Exit(code=2) from exc

        return wrapper

    return decorator


def handle_pipeline_errors(*, step_name: str, success_exit_code: int = 0, unknown_exit_code: int = 2) -> Callable:
    """Convert known exceptions in a multi-step pipeline into clean exits.

    Maps:
      * ``FileNotFoundError`` / ``ValueError`` -> exit 2 (input error)
      * ``RuntimeError`` -> exit 10 (backend / API failure)
      * anything else -> ``unknown_exit_code`` (default 2)

    ``typer.Exit`` (raised explicitly inside the wrapped function for normal
    flow control — e.g. early validation failure with the spec exit code)
    is re-raised unchanged so the caller can still control its own exit code.

    Use this around an ``audit baseline`` / ``audit run`` step that calls
    ``run_audit`` and expects to translate failures to a CLI exit code.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from typer import Exit

            try:
                return func(*args, **kwargs)
            except Exit:
                # Explicit exits (validation failures, normal flow control)
                # bubble up unchanged so the caller keeps its exit code.
                raise
            except (FileNotFoundError, ValueError) as exc:
                rprint(f"[red]Audit pipeline error:[/red] {exc}")
                raise Exit(code=2) from exc
            except RuntimeError as exc:
                rprint(f"[red]Audit pipeline error:[/red] {exc}")
                raise Exit(code=10) from exc
            except Exception as exc:
                rprint(f"[red]Audit pipeline error:[/red] {exc}")
                raise Exit(code=unknown_exit_code) from exc

        return wrapper

    return decorator


def handle_compare_errors(*, source_label: str = "input") -> Callable:
    """Error handler for ``audit compare``: split backend vs input failures.

    Maps:
      * ``json.JSONDecodeError`` / ``ValueError`` / ``FileNotFoundError`` -> exit 2
      * ``RuntimeError`` -> exit 10 (PageSpeed API failure)
      * other -> exit 2

    ``typer.Exit`` raised explicitly inside the wrapped function bubbles up
    unchanged.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from typer import Exit

            try:
                return func(*args, **kwargs)
            except Exit:
                raise
            except (json.JSONDecodeError, ValueError) as exc:
                rprint(f"[red]Error:[/red] Invalid {source_label}: {exc}")
                raise Exit(code=2) from exc
            except FileNotFoundError as exc:
                rprint(f"[red]Error:[/red] {exc}")
                raise Exit(code=2) from exc
            except RuntimeError as exc:
                rprint(f"[red]Error:[/red] Backend failure: {exc}")
                raise Exit(code=10) from exc
            except Exception as exc:
                rprint(f"[red]Error:[/red] Failed to compare audits: {exc}")
                raise Exit(code=2) from exc

        return wrapper

    return decorator


def handle_shopify_errors() -> Callable:
    """Error handler for ``audit shopify auth`` / ``audit shopify inventory``.

    Maps:
      * ``ValueError`` -> exit 2 (invalid input)
      * ``RuntimeError`` -> exit 10 (Shopify API failure)
      * other -> exit 10 (treated as backend failure)

    ``typer.Exit`` raised explicitly bubbles up unchanged.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from typer import Exit

            try:
                return func(*args, **kwargs)
            except Exit:
                raise
            except ValueError as exc:
                rprint(f"[red]Error:[/red] Invalid input: {exc}")
                raise Exit(code=2) from exc
            except RuntimeError as exc:
                rprint(f"[red]Error:[/red] Shopify API error: {exc}")
                raise Exit(code=10) from exc
            except Exception as exc:
                rprint(f"[red]Error:[/red] Failed to reach Shopify: {exc}")
                raise Exit(code=10) from exc

        return wrapper

    return decorator
