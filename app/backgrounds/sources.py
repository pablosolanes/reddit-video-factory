from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackgroundSearchItem:
    source_url: str
    source_platform: str
    title: str
    author: str | None
    license: str | None
    license_status: str
    category: str
    subcategory: str | None = None


class BackgroundSource(ABC):
    @abstractmethod
    def search(self, query: str) -> list[BackgroundSearchItem]:
        """Return license-aware downloadable items for a query."""

    @abstractmethod
    def download(self, item: BackgroundSearchItem, output_dir: Path) -> Path:
        """Download one permitted item and return the local path."""


class NoConfiguredSources(BackgroundSource):
    def search(self, query: str) -> list[BackgroundSearchItem]:
        return []

    def download(self, item: BackgroundSearchItem, output_dir: Path) -> Path:
        raise RuntimeError("No background sources are configured.")

