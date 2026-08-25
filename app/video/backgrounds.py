from __future__ import annotations

import random
import subprocess
from pathlib import Path

from app.config import BackgroundsConfig, VideoConfig


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


class BackgroundSelectionError(RuntimeError):
    """Raised when no usable local background video is available."""


class BackgroundSelector:
    def __init__(self, config: BackgroundsConfig, video_config: VideoConfig) -> None:
        self.config = config
        self.video_config = video_config

    def select(self, avoid_path: str | None = None) -> Path:
        candidates = self._find_candidates()
        if self.config.avoid_consecutive_repeats and avoid_path and len(candidates) > 1:
            avoided = Path(avoid_path).resolve()
            candidates = [path for path in candidates if path.resolve() != avoided]

        valid_candidates = [path for path in candidates if self.is_usable(path)]
        if not valid_candidates:
            raise BackgroundSelectionError(
                f"No usable background videos found in {self.config.directory}. "
                "Place local MP4/MOV/MKV/WEBM files under backgrounds/."
            )
        return random.choice(valid_candidates)

    def _find_candidates(self) -> list[Path]:
        if not self.config.directory.exists():
            return []
        return sorted(
            path
            for path in self.config.directory.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        )

    def is_usable(self, path: Path) -> bool:
        try:
            duration = self._probe_duration(path)
        except Exception:
            return False
        return duration >= 5.0

    def _probe_duration(self, path: Path) -> float:
        command = [
            self.video_config.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
