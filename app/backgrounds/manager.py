from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from app.config import BackgroundsConfig, VideoConfig
from app.database import upsert_background


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


class BackgroundLibraryManager:
    def __init__(self, backgrounds_config: BackgroundsConfig, video_config: VideoConfig) -> None:
        self.backgrounds_config = backgrounds_config
        self.video_config = video_config

    def index_local_library(self, connection) -> int:
        indexed = 0
        for path in self._find_files():
            metadata = self.probe(path)
            status = "available" if self.meets_quality(metadata) else "rejected"
            upsert_background(
                connection,
                {
                    "filename": path.name,
                    "filepath": str(path),
                    "category": self._category_for_path(path),
                    "subcategory": self._subcategory_for_path(path),
                    "source_url": None,
                    "source_platform": "manual",
                    "author": None,
                    "license": None,
                    "license_status": "manual",
                    "downloaded_at": None,
                    "duration": metadata["duration"],
                    "width": metadata["width"],
                    "height": metadata["height"],
                    "file_hash": self.file_hash(path),
                    "status": status,
                },
            )
            indexed += 1
        return indexed

    def probe(self, path: Path) -> dict:
        command = [
            self.video_config.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            return {"duration": 0.0, "width": 0, "height": 0}
        if result.returncode != 0:
            return {"duration": 0.0, "width": 0, "height": 0}

        import json

        data = json.loads(result.stdout)
        video_stream = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
        return {
            "duration": float(data.get("format", {}).get("duration", 0.0) or 0.0),
            "width": int(video_stream.get("width", 0) or 0),
            "height": int(video_stream.get("height", 0) or 0),
        }

    def meets_quality(self, metadata: dict) -> bool:
        return (
            float(metadata["duration"]) >= self.backgrounds_config.min_duration_seconds
            and int(metadata["width"]) >= self.backgrounds_config.min_width
            and int(metadata["height"]) >= self.backgrounds_config.min_height
        )

    def file_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _find_files(self) -> list[Path]:
        root = self.backgrounds_config.directory
        if not root.exists():
            return []
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        )

    def _category_for_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.backgrounds_config.directory)
        except ValueError:
            return self.backgrounds_config.default_category
        return relative.parts[0] if len(relative.parts) > 1 else self.backgrounds_config.default_category

    def _subcategory_for_path(self, path: Path) -> str | None:
        lowered = path.stem.lower()
        for token in ("parkour", "survival", "building", "dark", "nature", "relaxing"):
            if token in lowered:
                return token
        return None
