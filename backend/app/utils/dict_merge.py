"""Shared deep-merge helper used by taxonomy, needs extractor, and orchestrator.

Kept tiny, standalone, and dependency-free so it can be imported from any
service without creating a cycle with `profiler_agent.py`.

Merge semantics:
- Nested dicts are merged key-by-key.
- ``None`` values in ``incoming`` do not overwrite non-``None`` values in ``base``.
- Non-dict values in ``incoming`` overwrite the corresponding key in ``base``.
- Both inputs are treated as read-only; a fresh dict is returned.
"""

from __future__ import annotations

from typing import Any


def deep_merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        elif isinstance(value, dict):
            merged[key] = deep_merge_dicts({}, value)
        elif value is not None:
            merged[key] = value
    return merged
