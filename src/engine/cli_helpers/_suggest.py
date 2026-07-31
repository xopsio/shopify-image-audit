"""
"Did you mean..." suggestions for CLI typos (Sprint 8, TD-1).

Wraps :func:`difflib.get_close_matches` with a strict cutoff and a
single-result contract so callers can drop the suggestion into an error
message: ``"Invalid value 'mobilo'; did you mean: mobile?"``.

Used by every CLI command that validates against a fixed enum
(``--device``, ``--strategy``, ``--ranker``, ``shopify <subcommand>``,
``history <subcommand>``, ``schedule <subcommand>``).
"""

from __future__ import annotations

from difflib import get_close_matches

#: Cutoff for :func:`difflib.get_close_matches`. 0.6 is the stdlib
#: default and produces useful suggestions without false positives on
#: short enum values like "ml".
_DEFAULT_CUTOFF = 0.6


def suggest_close_match(
    needle: str,
    choices: list[str],
    *,
    cutoff: float = _DEFAULT_CUTOFF,
) -> str | None:
    """Return the closest match for ``needle`` in ``choices``, or None.

    Comparison is case-sensitive (consistent with how the CLI validates
    enum values like ``"mobile"`` vs ``"desktop"``). Returns the single
    best match above ``cutoff`` (``0.0`` → 1.0, higher = stricter).

    Examples::

        >>> suggest_close_match("mobilo", ["mobile", "desktop"])
        'mobile'

        >>> suggest_close_match("auth", ["inventory", "batch"])
        'inventory'  # best match for the prefix
    """
    if not needle or not choices:
        return None
    matches = get_close_matches(needle, choices, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def format_suggestion(needle: str, choices: list[str]) -> str:
    """Return the ``Did you mean: X?`` suffix, or empty string.

    Helper so callers can write::
        rprint(f"Error: ...\\n{format_suggestion(value, VALID)}")
    """
    suggestion = suggest_close_match(needle, choices)
    if suggestion is None:
        return ""
    return f" Did you mean: {suggestion}?"
