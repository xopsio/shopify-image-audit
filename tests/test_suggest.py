"""
Tests for ``src/engine/cli_helpers/_suggest.py`` (Sprint 8, TD-1).
"""

from __future__ import annotations

from engine.cli_helpers._suggest import (
    format_suggestion,
    suggest_close_match,
)


class TestSuggestCloseMatch:
    def test_exact_match_returns_it(self) -> None:
        assert suggest_close_match("mobile", ["mobile", "desktop"]) == "mobile"

    def test_one_letter_typo(self) -> None:
        assert suggest_close_match("mobilo", ["mobile", "desktop"]) == "mobile"

    def test_two_letter_typo(self) -> None:
        assert suggest_close_match("desktopo", ["mobile", "desktop"]) == "desktop"

    def test_transposition(self) -> None:
        assert suggest_close_match("moible", ["mobile", "desktop"]) == "mobile"

    def test_far_match_returns_none(self) -> None:
        # Completely different word — beyond the cutoff.
        assert suggest_close_match("zzz", ["mobile", "desktop"]) is None

    def test_empty_needle_returns_none(self) -> None:
        assert suggest_close_match("", ["mobile"]) is None

    def test_empty_choices_returns_none(self) -> None:
        assert suggest_close_match("mobile", []) is None

    def test_case_sensitive(self) -> None:
        # Enum values are lowercase; uppercase typo is far away.
        assert suggest_close_match("MOBILE", ["mobile", "desktop"]) is None

    def test_custom_cutoff(self) -> None:
        # Stricter cutoff rejects the match.
        assert suggest_close_match("desktopo", ["mobile", "desktop"], cutoff=0.95) is None

    def test_prefers_close_over_far(self) -> None:
        # "mobilo" is closer to "mobile" than to "molecule".
        result = suggest_close_match("mobilo", ["mobile", "molecule"])
        assert result == "mobile"

    def test_three_way_choice(self) -> None:
        # Best match from three options.
        result = suggest_close_match("instry", ["inventory", "batch", "auth"])
        assert result == "inventory"


class TestFormatSuggestion:
    def test_with_suggestion(self) -> None:
        out = format_suggestion("mobilo", ["mobile", "desktop"])
        assert out == " Did you mean: mobile?"

    def test_without_suggestion(self) -> None:
        # No match → empty string (NOT "Did you mean: ?").
        assert format_suggestion("xyz", ["mobile", "desktop"]) == ""

    def test_empty_choices(self) -> None:
        assert format_suggestion("anything", []) == ""
