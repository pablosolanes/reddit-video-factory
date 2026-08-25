from __future__ import annotations

import json
from pathlib import Path

from app.config import BackgroundsConfig, VideoConfig
from app.database import find_backgrounds


class StoryVisualProfile:
    def __init__(self, category: str, style: str, mood: str, color_style: str, subtitle_style: str) -> None:
        self.category = category
        self.style = style
        self.mood = mood
        self.color_style = color_style
        self.subtitle_style = subtitle_style

    @classmethod
    def from_json(cls, value: str | None, defaults: BackgroundsConfig, subtitle_style: str = "style_01"):
        if value:
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        return cls(
            category=str(data.get("category") or defaults.default_category),
            style=str(data.get("style") or defaults.default_style),
            mood=str(data.get("mood") or "neutral"),
            color_style=str(data.get("color_style") or "normal"),
            subtitle_style=str(data.get("subtitle_style") or subtitle_style),
        )

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "style": self.style,
            "mood": self.mood,
            "color_style": self.color_style,
            "subtitle_style": self.subtitle_style,
        }


class BackgroundSelectionError(RuntimeError):
    """Raised when no compatible background is available."""


class BackgroundSelector:
    def __init__(self, backgrounds_config: BackgroundsConfig, video_config: VideoConfig) -> None:
        self.backgrounds_config = backgrounds_config
        self.video_config = video_config

    def select_for_story(self, connection, visual_profile: StoryVisualProfile) -> Path:
        exact = find_backgrounds(connection, visual_profile.category, visual_profile.style)
        if exact:
            return Path(exact[0]["filepath"])

        category_matches = find_backgrounds(connection, visual_profile.category)
        if category_matches:
            return Path(category_matches[0]["filepath"])

        raise BackgroundSelectionError(
            f"No available backgrounds for category={visual_profile.category} style={visual_profile.style}"
        )
