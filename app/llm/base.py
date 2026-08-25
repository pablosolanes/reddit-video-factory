from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    def select_stories(self, candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        """Select stories with strong narrative potential."""

    @abstractmethod
    def generate_script(self, story: dict[str, Any]) -> dict[str, Any]:
        """Generate a structured script JSON payload."""

    @abstractmethod
    def cache_path_for_story(self, story: dict[str, Any]) -> Path:
        """Return the cache path used for a story script generation."""
