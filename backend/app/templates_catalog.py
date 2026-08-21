from __future__ import annotations

from typing import Any


TEMPLATES: list[dict[str, Any]] = [
    {"id": "clean-podcast", "name": "Clean Podcast", "description": "Readable captions, restrained crop, no extra effects.", "premium": False, "settings": {"caption_style": "clean", "caption_position": "bottom", "format": "9:16", "effects": {}}},
    {"id": "bold-creator", "name": "Bold Creator", "description": "High-contrast creator captions with subtle emphasis.", "premium": False, "settings": {"caption_style": "bold", "caption_position": "bottom", "format": "9:16", "effects": {"punch_zoom": True}}},
    {"id": "high-energy", "name": "High Energy", "description": "Premium caption treatment, fade, and punch zoom.", "premium": True, "settings": {"caption_style": "high-energy", "caption_position": "middle", "format": "9:16", "effects": {"punch_zoom": True, "fade": True}}},
    {"id": "minimal-square", "name": "Minimal Square", "description": "A premium clean square crop for feeds and carousels.", "premium": True, "settings": {"caption_style": "minimal", "caption_position": "bottom", "format": "1:1", "effects": {}}},
    {"id": "story-vertical", "name": "Story Vertical", "description": "A premium vertical story framing with safe captions.", "premium": True, "settings": {"caption_style": "podcast", "caption_position": "bottom", "format": "9:16", "effects": {"fade": True}}},
]


def list_templates() -> list[dict[str, Any]]:
    return TEMPLATES


def get_template(template_id: str) -> dict[str, Any] | None:
    return next((template for template in TEMPLATES if template["id"] == template_id), None)
