"""
JSON Schema validation tests.

Closes the QA_CHECKLIST.md gap: "Pydantic models validate output (or schema
validation passes)". These tests run the canonical ``jsonschema.validate``
against ``schemas/audit_result.schema.json`` for AuditResults produced by the
real pipeline on the existing fixtures.

The Pydantic models in ``audit.models`` mirror the schema, but this is the
independent cross-check that the *contract* (schema) and the *output*
(pipeline) agree.
"""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from engine.audit_orchestrator import run_audit
from tests import FIXTURES, REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "schemas" / "audit_result.schema.json"


@pytest.fixture(scope="module")
def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def validator(schema):
    # Building the validator once also validates the schema itself.
    return Draft202012Validator(schema)


@pytest.fixture(params=["bad_hero_lcp.json", "optimized_shopify.json"])
def audit_result(request: pytest.FixtureRequest):
    return run_audit(FIXTURES / request.param)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_schema_file_exists(self) -> None:
        assert SCHEMA_PATH.exists(), f"schema missing at {SCHEMA_PATH}"

    def test_schema_is_valid_draft(self, schema) -> None:
        # Raises if the schema document itself is malformed.
        Draft202012Validator.check_schema(schema)

    def test_audit_result_matches_schema(self, validator, audit_result) -> None:
        errors = sorted(validator.iter_errors(audit_result.model_dump()), key=lambda e: e.path)
        assert not errors, (
            "AuditResult failed schema validation:\n"
            + "\n".join(f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        )

    def test_no_additional_properties_at_root(self, validator) -> None:
        result = run_audit(FIXTURES / "bad_hero_lcp.json")
        payload = dict(result.model_dump())
        payload["unexpected_top_field"] = "should be rejected"
        errors = list(validator.iter_errors(payload))
        assert any("unexpected_top_field" in e.message for e in errors)

    def test_image_extra_field_rejected(self, validator) -> None:
        result = run_audit(FIXTURES / "bad_hero_lcp.json")
        payload = result.model_dump()
        payload["images"][0]["bogus_field"] = 123
        errors = list(validator.iter_errors(payload))
        assert any("bogus_field" in e.message for e in errors)

    def test_score_out_of_range_rejected(self, validator) -> None:
        result = run_audit(FIXTURES / "bad_hero_lcp.json")
        payload = result.model_dump()
        payload["images"][0]["score"] = 150  # maximum is 100
        errors = list(validator.iter_errors(payload))
        assert errors, "score=150 should violate the schema maximum"
