from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> float:
        """Generate audio and return duration in seconds."""

    @abstractmethod
    def cache_path_for_text(self, text: str, stem: str) -> Path:
        """Return the cache path used for a TTS input."""
