from __future__ import annotations

from pathlib import Path

from app.config import BackgroundDownloadConfig
from app.backgrounds.sources import BackgroundSource


class BackgroundDownloadDisabled(RuntimeError):
    """Raised when automatic background download is disabled."""


class BackgroundDownloader:
    def __init__(self, config: BackgroundDownloadConfig, sources: list[BackgroundSource] | None = None) -> None:
        self.config = config
        self.sources = sources or []

    def ensure_available(self, category: str, output_dir: Path) -> list[Path]:
        if not self.config.enabled:
            raise BackgroundDownloadDisabled("background_download.enabled is false")

        downloaded: list[Path] = []
        for source in self.sources:
            for item in source.search(category):
                if item.license_status != "known" or not item.license:
                    continue
                downloaded.append(source.download(item, output_dir))
        return downloaded

