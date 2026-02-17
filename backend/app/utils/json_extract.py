from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractionError(ValueError):
    pass


def extract_first_json(raw_text: str) -> Any:
    text = raw_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.findall(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    for candidate in fenced:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    candidate = _first_balanced_json_block(text)
    if candidate is None:
        raise JSONExtractionError("No JSON object found in model output.")

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JSONExtractionError("Found JSON-like block but failed to parse it.") from exc


def _first_balanced_json_block(text: str) -> str | None:
    start_idx = None
    stack: list[str] = []
    in_string = False
    escape = False

    for idx, char in enumerate(text):
        if start_idx is None and char in "[{":
            start_idx = idx
            stack.append("}" if char == "{" else "]")
            continue

        if start_idx is None:
            continue

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char in "[{":
            stack.append("}" if char == "{" else "]")
            continue

        if char in "}]":
            if not stack or char != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return text[start_idx : idx + 1]

    return None
