from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import VideoConfig


class VideoRenderError(RuntimeError):
    """Raised when FFmpeg rendering or validation fails."""


@dataclass(frozen=True)
class RenderResult:
    video_path: Path
    metadata_path: Path
    duration: float


class VideoRenderer:
    def __init__(self, config: VideoConfig) -> None:
        self.config = config

    def render(
        self,
        background_path: str | Path,
        audio_path: str | Path,
        subtitle_path: str | Path,
        output_path: str | Path,
        metadata_path: str | Path,
        metadata: dict[str, Any],
        style: str,
        part_label: str,
    ) -> RenderResult:
        background_path = Path(background_path)
        audio_path = Path(audio_path)
        subtitle_path = Path(subtitle_path)
        output_path = Path(output_path)
        metadata_path = Path(metadata_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if not background_path.exists():
            raise FileNotFoundError(f"Background not found: {background_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")
        if not subtitle_path.exists():
            raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

        duration = float(metadata["duration"])
        command = self._build_command(
            background_path=background_path,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            duration=duration,
            style=style,
            part_label=part_label,
        )
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise VideoRenderError(f"FFmpeg failed: {result.stderr[-2000:]}")

        validation = self.validate(output_path)
        self._validate_rendered_video(validation, duration)
        metadata["duration"] = validation["duration"]
        with metadata_path.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

        return RenderResult(
            video_path=output_path,
            metadata_path=metadata_path,
            duration=float(validation["duration"]),
        )

    def validate(self, video_path: str | Path) -> dict[str, Any]:
        path = Path(video_path)
        if not path.exists() or path.stat().st_size == 0:
            raise VideoRenderError(f"Rendered video does not exist or is empty: {path}")

        command = [
            self.config.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise VideoRenderError(f"ffprobe failed: {result.stderr[-2000:]}")

        probe = json.loads(result.stdout)
        video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), None)
        audio_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
        if not video_stream:
            raise VideoRenderError("Rendered MP4 has no video stream")
        if not audio_stream:
            raise VideoRenderError("Rendered MP4 has no audio stream")

        return {
            "duration": float(probe.get("format", {}).get("duration", 0.0) or 0.0),
            "width": int(video_stream.get("width", 0) or 0),
            "height": int(video_stream.get("height", 0) or 0),
            "video_codec": str(video_stream.get("codec_name", "")),
            "audio_codec": str(audio_stream.get("codec_name", "")),
        }

    def _build_command(
        self,
        background_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        duration: float,
        style: str,
        part_label: str,
    ) -> list[str]:
        video_filter = self._video_filter(subtitle_path, style, part_label)
        return [
            self.config.ffmpeg_path,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(background_path),
            "-i",
            str(audio_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.config.fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]

    def _video_filter(self, subtitle_path: Path, style: str, part_label: str) -> str:
        escaped_subtitles = self._escape_filter_path(subtitle_path)
        zoom = {
            "style_01": "1.000",
            "style_02": "1.030",
            "style_03": "1.060",
        }.get(style, "1.000")
        base = (
            f"scale={self.config.width}:{self.config.height}:force_original_aspect_ratio=increase,"
            f"crop={self.config.width}:{self.config.height},"
            f"scale=iw*{zoom}:ih*{zoom},"
            f"crop={self.config.width}:{self.config.height},"
            f"setsar=1,fps={self.config.fps},"
            f"subtitles=filename='{escaped_subtitles}'"
        )
        return base + "," + self._part_label_filter(part_label)

    def _part_label_filter(self, part_label: str) -> str:
        escaped_label = self._escape_drawtext(part_label)
        return (
            "drawtext="
            f"text='{escaped_label}':"
            "fontcolor=white:"
            "fontsize=44:"
            "box=1:"
            "boxcolor=black@0.45:"
            "boxborderw=18:"
            "x=(w-text_w)/2:"
            "y=h-360"
        )

    def _validate_rendered_video(self, validation: dict[str, Any], expected_duration: float) -> None:
        max_duration = self.config.max_duration_seconds + self.config.duration_tolerance_seconds
        if validation["duration"] < self.config.min_duration_seconds:
            raise VideoRenderError(f"Video duration too short: {validation['duration']:.2f}s")
        if validation["duration"] > max_duration:
            raise VideoRenderError(f"Video duration too long: {validation['duration']:.2f}s")
        if validation["width"] != self.config.width or validation["height"] != self.config.height:
            raise VideoRenderError(
                f"Invalid resolution: {validation['width']}x{validation['height']}"
            )
        if validation["video_codec"] != "h264":
            raise VideoRenderError(f"Invalid video codec: {validation['video_codec']}")
        if validation["audio_codec"] != "aac":
            raise VideoRenderError(f"Invalid audio codec: {validation['audio_codec']}")
        if abs(validation["duration"] - expected_duration) > self.config.duration_tolerance_seconds:
            raise VideoRenderError(
                f"Rendered duration {validation['duration']:.2f}s differs from audio {expected_duration:.2f}s"
            )

    def _escape_filter_path(self, path: Path) -> str:
        value = path.resolve().as_posix()
        return value.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    def _escape_drawtext(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
