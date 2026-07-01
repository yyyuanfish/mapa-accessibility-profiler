from __future__ import annotations

from backend.app.providers.image_provider import MockImageProvider, OllamaImageProvider


def test_image_provider_normalizes_symbolic_vision_feedback() -> None:
    provider = OllamaImageProvider()

    result = provider._normalize_hazards(
        {
            "stairs": "high",
            "slope": "low",
            "crowd": "none",
            "scene_summary": "Stairs are visible near the entrance.",
            "visible_objects": ["stairs", "handrail", "stairs"],
            "accessibility_cues": ["stairs visible", "handrail visible"],
            "reasoning_steps": ["Observed stairs in the visible path."],
            "evidence": ["visible objects: stairs, handrail"],
            "notes": ["Use route metadata as the primary accessibility signal."],
        }
    )

    assert result.scene_summary == "Stairs are visible near the entrance."
    assert result.visible_objects == ["stairs", "handrail"]
    assert result.accessibility_cues == ["stairs visible", "handrail visible"]
    assert result.reasoning_steps == ["Observed stairs in the visible path."]
    assert result.evidence == ["visible objects: stairs, handrail"]


def test_mock_image_provider_returns_symbolic_feedback() -> None:
    provider = MockImageProvider()

    result = provider.summarize_hazards(b"synthetic-image-bytes")

    assert result.scene_summary is not None
    assert isinstance(result.visible_objects, list)
    assert isinstance(result.accessibility_cues, list)
    assert isinstance(result.reasoning_steps, list)
    assert isinstance(result.evidence, list)
