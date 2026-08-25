from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Publisher(ABC):
    @abstractmethod
    def publish(self, video_path: Path, title: str, description: str) -> None:
        """Publish a generated video through an official platform API."""

