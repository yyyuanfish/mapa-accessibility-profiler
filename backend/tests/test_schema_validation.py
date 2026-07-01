from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from backend.app.models import AccessibilityProfile


def test_profile_model_validates_against_json_schema() -> None:
    schema_path = Path("backend/app/schemas/accessibility_profile.schema.json")
    schema = json.loads(schema_path.read_text())

    profile = AccessibilityProfile().model_dump()
    validate(instance=profile, schema=schema)


def test_schema_contains_required_sign_gloss_enum() -> None:
    schema_path = Path("backend/app/schemas/accessibility_profile.schema.json")
    schema = json.loads(schema_path.read_text())

    output_mode_enum = schema["properties"]["communication"]["properties"]["output_mode"]["enum"]
    assert "sign_gloss_text" in output_mode_enum
