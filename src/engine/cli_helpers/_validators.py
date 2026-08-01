"""
CLI input validation helpers.

Extracted from the monolithic ``cli.py`` to make the command bodies thin and
the validation logic independently testable.

Conventions:
- Functions raise ``typer.Exit(code=2)`` on failure; they print a single red
  error line via the shared console. The caller does not need to wrap in
  try/except.
- Functions return the validated ``Path`` (or normalized form) so the caller
  can use it directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from rich import print as rprint

# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _is_windows_absolute_path(path_str: str) -> bool:
    """True if ``path_str`` looks like a Windows drive-letter absolute path (e.g. ``C:\\foo``)."""
    if os.name != "nt":
        return False
    return len(path_str) >= 2 and path_str[1:2] == ":"


def validate_out_path(out_path: Path | str, *, label: str = "--output") -> Path:
    """Validate that an output path is safe: relative, no ``..`` segments, within cwd.

    Args:
        out_path: candidate output path (relative).
        label: flag name to mention in error messages (e.g. ``--output``, ``--out-dir``).

    Returns:
        The ``Path`` form of the input.

    Raises:
        typer.Exit: with exit code 2 if the path fails any safety check.
    """
    from typer import Exit  # local import keeps typer dep optional for non-CLI tests

    out_path_p = Path(out_path)
    out_path_str = str(out_path_p)

    if out_path_p.is_absolute():
        rprint(f"[red]Error:[/red] {label} must be a relative path.")
        raise Exit(code=2)

    if _is_windows_absolute_path(out_path_str) or out_path_str.startswith("\\") or ":\\" in out_path_str:
        rprint(f"[red]Error:[/red] {label} must be a relative path.")
        raise Exit(code=2)

    if ".." in out_path_p.parts:
        rprint(f"[red]Error:[/red] {label} must not contain '..' segments.")
        raise Exit(code=2)

    resolved_out = Path.cwd().joinpath(out_path_p).resolve()
    cwd_resolved = Path.cwd().resolve()

    try:
        resolved_out.relative_to(cwd_resolved)
    except ValueError:
        rprint(f"[red]Error:[/red] {label} resolves outside the working directory.")
        raise Exit(code=2) from None

    return out_path_p


def require_exists(path: Path | str, *, label: str = "File") -> Path:
    """Ensure a file path exists; otherwise print a red error and exit 2.

    Args:
        path: candidate file path.
        label: noun to use in the error message (``"File"``, ``"baseline file"``, ...).

    Returns:
        The ``Path`` form of the input.
    """
    from typer import Exit

    path_p = Path(path)
    if not path_p.exists():
        rprint(f"[red]Error:[/red] {label} not found: {path_p}")
        raise Exit(code=2)
    return path_p


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def validate_url_scheme(url: str, *, allow_scheme_less: bool = False) -> None:
    """Validate a URL's scheme. Exits 2 on invalid input.

    Args:
        url: candidate URL.
        allow_scheme_less: if True, scheme-less URLs (e.g. ``example.com``) are allowed
            and will be normalized to ``https://`` by the caller.
    """
    from typer import Exit

    parsed = urlparse(url)
    if allow_scheme_less:
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            rprint(f"[red]Error:[/red] URL scheme must be http or https, got '{parsed.scheme}'.")
            raise Exit(code=2)
        if not parsed.netloc and not parsed.path:
            rprint("[red]Error:[/red] URL must include a hostname.")
            raise Exit(code=2)
    else:
        if parsed.scheme not in ("http", "https"):
            scheme_display = parsed.scheme or "(empty)"
            rprint(f"[red]Error:[/red] URL scheme must be http or https, got '{scheme_display}'.")
            raise Exit(code=2)


# Convenience wrappers for the two original validators (kept for clarity at call sites)


def validate_run_url(url: str) -> None:
    """``audit run`` URL validation: explicit http/https only."""
    validate_url_scheme(url, allow_scheme_less=False)


def validate_measure_url(url: str) -> None:
    """``audit measure`` URL validation: scheme-less URLs allowed (PageSpeed normalizes)."""
    validate_url_scheme(url, allow_scheme_less=True)
